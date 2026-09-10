import base64

import pytest

from tevion_api.provider import GPTImageProvider, ProviderResponseError


def test_provider_normalizes_b64_json_response() -> None:
    provider = GPTImageProvider(endpoint="https://example.test/images", api_key="secret")
    encoded = base64.b64encode(b"png").decode()
    result = provider.normalize_response({"id": "request-1", "data": [{"b64_json": encoded}]}, latency_ms=1)

    assert result.asset_urls == [f"data:image/png;base64,{encoded}"]
    assert result.asset_mime_types == ["image/png"]


def test_provider_rejects_invalid_b64_json_response() -> None:
    provider = GPTImageProvider(endpoint="https://example.test/images", api_key="secret")
    with pytest.raises(ProviderResponseError, match="base64"):
        provider.normalize_response({"id": "request-1", "data": [{"b64_json": "not base64!"}]}, latency_ms=1)
