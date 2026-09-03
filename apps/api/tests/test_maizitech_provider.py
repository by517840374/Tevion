import json
from collections.abc import Callable

import httpx
import pytest

from tevion_api.provider import (
    GenerationRequest,
    MaizitechImageProvider,
    ProviderConfigError,
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
                json={"created": 1714012800, "data": [{"task_id": "task_abc", "status": "pending"}]},
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
    assert result.asset_urls == ["https://cdn.example.test/result-1.png"]
    assert result.cost == 0.0081
    assert result.metadata == {"provider": "maizitech", "params": {"size": "1:1", "quality": "low"}, "size": "1:1"}
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
        return httpx.Response(
            200, json={"id": "task_bad", "status": "failed", "error_msg": f"boom {API_KEY}"}
        )

    provider = _provider(handler)
    with pytest.raises(ProviderResponseError) as exc:
        provider.generate(GenerationRequest(prompt="x", output_count=1))
    assert API_KEY not in str(exc.value)


def test_sync_style_response_with_immediate_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"created": 1, "data": [{"url": "https://cdn.example.test/direct.png"}]}
        )

    provider = _provider(handler)
    result = provider.generate(GenerationRequest(prompt="x", output_count=1))
    assert result.asset_urls == ["https://cdn.example.test/direct.png"]


def test_http_error_propagates_and_config_requires_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    provider = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        provider.generate(GenerationRequest(prompt="x", output_count=1))

    with pytest.raises(ProviderConfigError):
        MaizitechImageProvider(api_key="  ", http_client=httpx.Client())
