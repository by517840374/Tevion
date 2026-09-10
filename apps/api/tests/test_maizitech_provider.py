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
    assert result.requested_count == 2
    assert result.actual_count == 1
    assert result.completeness == "partial"
    assert result.shortfall == 1
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


def test_uploads_parent_as_image_multipart_and_returns_https_url() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/files/upload")
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(200, json={"url": "https://files.maizi.test/parent.png", "cost": 0})

    result = _provider(handler).upload_image(b"png-bytes", "image/png")

    assert result.url == "https://files.maizi.test/parent.png"
    assert "multipart/form-data" in str(seen["content_type"])
    body = bytes(seen["body"])
    assert b'name="type"' in body and b"image" in body
    assert b'name="file"' in body and b"png-bytes" in body


def test_upload_retries_bounded_409_using_retry_after() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(409, headers={"Retry-After": "0"}, json={"error": "uploading"})
        return httpx.Response(200, json={"url": "https://files.maizi.test/reused.png", "task_id": "upload-1"})

    result = _provider(handler).upload_image(b"bytes", "image/jpeg")

    assert result.url == "https://files.maizi.test/reused.png"
    assert result.task_id == "upload-1"
    assert attempts == 3


def test_edit_uploads_parent_then_sends_image_reference() -> None:
    requests: list[tuple[str, dict | bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files/upload"):
            requests.append((request.url.path, request.content))
            return httpx.Response(200, json={"url": "https://files.maizi.test/parent.png", "cost": 0})
        if request.url.path.endswith("/images/generations"):
            payload = json.loads(request.content)
            requests.append((request.url.path, payload))
            return httpx.Response(200, json={"data": [{"task_id": "task-edit", "status": "pending"}]})
        assert request.url.path.endswith("/tasks/task-edit")
        return httpx.Response(200, json={"status": "completed", "result_urls": ["https://files.maizi.test/result.png"]})

    result = _provider(handler).edit_image(
        prompt="保持人物身份，换成户外光线",
        image=b"parent-bytes",
        mime_type="image/png",
        parent_image_id="image_parent",
        parent_run_id="run_parent",
        owner_id="user_owner",
    )

    assert result.provider_request_id == "task-edit"
    assert requests[0][0].endswith("/files/upload")
    payload = requests[1][1]
    assert isinstance(payload, dict)
    assert payload["image"] == ["https://files.maizi.test/parent.png"]
    assert "n" not in payload
    assert result.cost is None
    assert result.metadata["upload_cost"] == 0
    assert result.metadata["parent_image_id"] == "image_parent"
