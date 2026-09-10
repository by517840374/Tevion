import json

import httpx
import pytest

from tevion_api.provider import GenerationRequest, PixhubImageProvider, ProviderConfigError, ProviderResponseError

API_KEY = "pixhub-test-key"


def _provider(handler):
    return PixhubImageProvider(
        api_key=API_KEY,
        base_url="https://pixhub.example.test/v1",
        model_name="gpt-image-2.5",
        response_format="url",
        default_size="1024x1024",
        quality="high",
        timeout_seconds=7,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_pixhub_posts_fixed_single_output_and_normalizes_url_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"id": "pix-123", "model": "gpt-image-2.5", "data": [{"url": "https://tmp.test/a.png"}]}
        )

    result = _provider(handler).generate(
        GenerationRequest(prompt="portrait", output_count=4, aspect_ratio="4:5", quality="low")
    )

    assert seen["url"] == "https://pixhub.example.test/v1/images/generations"
    assert seen["body"] == {
        "model": "gpt-image-2.5",
        "prompt": "portrait",
        "n": 1,
        "size": "1024x1024",
        "quality": "low",
        "response_format": "url",
    }
    assert seen["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert API_KEY not in json.dumps(seen["body"])
    assert result.asset_urls == ["https://tmp.test/a.png"]
    assert result.requested_count == 4
    assert result.actual_count == 1
    assert result.completeness == "partial"
    assert result.metadata == {"asset_persistence": "temporary_provider_url"}


def test_pixhub_normalizes_b64_response_as_explicit_temporary_data_asset():
    provider = PixhubImageProvider(api_key=API_KEY, base_url="https://pixhub.test", response_format="b64_json")

    result = provider.normalize_response(
        {"id": "pix-b64", "data": [{"b64_json": "ZmFrZQ=="}]}, latency_ms=2, requested_count=1
    )

    assert result.asset_urls == ["data:image/png;base64,ZmFrZQ=="]
    assert result.metadata == {"asset_persistence": "temporary_base64"}


def test_pixhub_maps_request_model_size_quality_and_response_format():
    provider = PixhubImageProvider(
        api_key=API_KEY,
        base_url="https://pixhub.test/v1",
        model_name="gpt-image-2.5",
        default_size="1536x1024",
        quality="medium",
        response_format="b64_json",
    )

    assert provider.build_payload(GenerationRequest(prompt="x", aspect_ratio="4:5", quality="low")) == {
        "model": "gpt-image-2.5",
        "prompt": "x",
        "n": 1,
        "size": "1536x1024",
        "quality": "low",
        "response_format": "b64_json",
    }


def test_pixhub_rejects_missing_configuration_and_malformed_data():
    with pytest.raises(ProviderConfigError):
        PixhubImageProvider(api_key="", base_url="https://pixhub.test")

    provider = PixhubImageProvider(api_key=API_KEY, base_url="https://pixhub.test")
    with pytest.raises(ProviderResponseError, match="asset"):
        provider.normalize_response({"id": "pix-1", "data": [{}]}, latency_ms=1)


def test_pixhub_errors_redact_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": f"bad {API_KEY}"}})

    with pytest.raises(ProviderResponseError) as exc:
        _provider(handler).generate(GenerationRequest(prompt="x"))
    assert API_KEY not in str(exc.value)
