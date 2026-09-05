import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tevion_api.provider import (
    GenerationRequest,
    MaizitechImageProvider,
    ProviderConfigError,
    ProviderOperationStatus,
    ProviderResponseError,
)

API_KEY = "sk-test-key-not-real-0123456789"

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler) -> MaizitechImageProvider:
    return MaizitechImageProvider(
        api_key=API_KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        poll_interval_seconds=0.01,
        timeout_seconds=5,
    )


def test_submit_poll_and_normalize_completed_task() -> None:
    seen_bodies: list[dict] = []
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            seen_bodies.append(json.loads(request.content))
            seen_auth.append(request.headers.get("authorization", ""))
            return httpx.Response(
                200,
                json={
                    "created": 1714012800,
                    "data": [{"task_id": "task_abc", "status": "pending"}],
                },
            )
        assert request.url.path.endswith("/tasks/task_abc")
        return httpx.Response(
            200,
            json={
                "id": "task_abc",
                "status": "completed",
                "model": "gpt-image-2",
                "result_urls": ["https://cdn.example.test/result-1.png"],
                "cost": 0.0081,
                "params": {"size": "1:1", "quality": "low"},
            },
        )

    provider = _provider(handler)
    result = provider.generate(
        GenerationRequest(prompt="清爽成年男性肖像", output_count=2, aspect_ratio="1:1", quality="low")
    )

    assert result.provider_request_id == "task_abc"
    assert result.provider_name == "maizitech"
    assert result.model_name == "gpt-image-2"
    assert result.metadata_source == "provider_response"
    assert result.asset_urls == ["https://cdn.example.test/result-1.png"]
    assert result.cost == 0.0081
    assert result.metadata == {
        "provider": "maizitech",
        "params": {"size": "1:1", "quality": "low"},
        "size": "1:1",
    }
    # payload carries model/prompt/n but never the api key
    assert seen_bodies[0]["model"] == "gpt-image-2"
    assert seen_bodies[0]["prompt"] == "清爽成年男性肖像"
    assert seen_bodies[0]["n"] == 2
    assert "api_key" not in seen_bodies[0]
    assert "sk-test" not in json.dumps(seen_bodies)
    assert seen_auth == [f"Bearer {API_KEY}"]


def test_failed_task_raises_without_exposing_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"task_id": "task_bad", "status": "pending"}]})
        return httpx.Response(200, json={"id": "task_bad", "status": "failed", "error_msg": f"boom {API_KEY}"})

    provider = _provider(handler)
    with pytest.raises(ProviderResponseError) as exc:
        provider.generate(GenerationRequest(prompt="x", output_count=1))
    assert API_KEY not in str(exc.value)


def test_sync_style_response_with_immediate_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": [{"url": "https://cdn.example.test/direct.png"}]})

    provider = _provider(handler)
    result = provider.generate(GenerationRequest(prompt="x", output_count=1))
    assert not hasattr(provider, "_immediate")
    assert result.provider_name == "maizitech"
    assert result.metadata_source == "provider_response"
    assert result.asset_urls == ["https://cdn.example.test/direct.png"]


def test_sync_results_do_not_leak_between_repeated_calls() -> None:
    responses = iter(
        [
            {"data": [{"url": "https://cdn.example.test/first.png"}]},
            {"data": [{"url": "https://cdn.example.test/second.png"}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    provider = _provider(handler)
    assert provider.generate(GenerationRequest(prompt="first")).asset_urls == ["https://cdn.example.test/first.png"]
    assert provider.generate(GenerationRequest(prompt="second")).asset_urls == ["https://cdn.example.test/second.png"]


def test_sync_results_are_isolated_for_concurrent_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["prompt"]
        return httpx.Response(200, json={"data": [{"url": f"https://cdn.example.test/{prompt}.png"}]})

    provider = _provider(handler)
    prompts = ["one", "two", "three", "four"]
    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
        results = list(executor.map(lambda prompt: provider.generate(GenerationRequest(prompt=prompt)), prompts))

    assert [result.asset_urls for result in results] == [
        [f"https://cdn.example.test/{prompt}.png"] for prompt in prompts
    ]


def test_metadata_redacts_secrets_and_raw_provider_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"task_id": "task_secret", "status": "pending"}]})

    provider = _provider(handler)
    provider._poll = lambda task_id: {  # type: ignore[method-assign]
        "status": "completed",
        "model": "gpt-image-2",
        "result_urls": ["https://cdn.example.test/result.png"],
        "params": {"size": "1:1"},
        "authorization": f"Bearer {API_KEY}",
        "raw_response": {"private_image": "data:image/png;base64,secret"},
    }

    result = provider.generate(GenerationRequest(prompt="x"))
    serialized = json.dumps(result.metadata or {})
    assert "authorization" not in serialized.lower()
    assert API_KEY not in serialized
    assert "private_image" not in serialized
    assert result.metadata == {"provider": "maizitech", "params": {"size": "1:1"}, "size": "1:1"}


def test_http_error_propagates_and_config_requires_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    provider = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        provider.generate(GenerationRequest(prompt="x", output_count=1))

    with pytest.raises(ProviderConfigError):
        MaizitechImageProvider(api_key="  ", http_client=httpx.Client())


def test_submit_returns_persistable_request_id_without_polling() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"data": [{"task_id": "task_submit", "status": "pending"}]})

    result = _provider(handler).submit(GenerationRequest(prompt="x"))

    assert result.status is ProviderOperationStatus.PENDING
    assert result.provider_request_id == "task_submit"
    assert calls == ["POST"]


def test_submit_response_loss_is_structured_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("connection lost after submit")

    result = _provider(handler).submit(GenerationRequest(prompt="x"))

    assert result.status is ProviderOperationStatus.UNKNOWN
    assert result.provider_request_id is None
    assert result.error_code == "submit_unknown"


def test_poll_timeout_keeps_request_id_and_is_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        raise httpx.ReadTimeout("poll timed out")

    result = _provider(handler).poll("task_poll")

    assert result.status is ProviderOperationStatus.UNKNOWN
    assert result.provider_request_id == "task_poll"
    assert result.error_code == "poll_unknown"


def test_poll_timeout_keeps_request_id_when_provider_stays_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"id": "task_wait", "status": "processing"})

    provider = MaizitechImageProvider(
        api_key=API_KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        poll_interval_seconds=0.01,
        timeout_seconds=0.02,
    )
    result = provider.poll("task_wait")

    assert result.status is ProviderOperationStatus.UNKNOWN
    assert result.provider_request_id == "task_wait"
    assert result.error_code == "poll_timeout"


def test_resume_completed_and_failed_only_query_provider() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.method)
        task_id = request.url.path.rsplit("/", 1)[-1]
        if task_id == "task_done":
            return httpx.Response(
                200,
                json={"id": task_id, "status": "completed", "result_urls": ["https://cdn.test/done.png"]},
            )
        return httpx.Response(200, json={"id": task_id, "status": "failed", "error_msg": "rejected"})

    provider = _provider(handler)
    completed = provider.resume("task_done")
    failed = provider.resume("task_failed")

    assert completed.status is ProviderOperationStatus.COMPLETED
    assert completed.provider_request_id == "task_done"
    assert completed.result is not None
    assert failed.status is ProviderOperationStatus.FAILED
    assert failed.provider_request_id == "task_failed"
    assert requested == ["GET", "GET"]
