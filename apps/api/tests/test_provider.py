import pytest

from tevion_api.provider import (
    GenerationRequest,
    GenerationResult,
    GPTImageProvider,
    ProviderConfigError,
    ProviderResponseError,
)


def test_generation_request_contains_product_level_fields() -> None:
    request = GenerationRequest(
        prompt="clearly adult male portrait, fresh youthful energy, cinematic light",
        output_count=2,
        aspect_ratio="4:5",
        strategy_version="strategy_v1",
    )

    assert request.output_count == 2
    assert request.aspect_ratio == "4:5"
    assert request.strategy_version == "strategy_v1"


def test_provider_requires_endpoint_and_api_key() -> None:
    with pytest.raises(ProviderConfigError, match="endpoint"):
        GPTImageProvider(endpoint="", api_key="secret")
    with pytest.raises(ProviderConfigError, match="API key"):
        GPTImageProvider(endpoint="https://example.test/images", api_key="")


def test_provider_normalizes_a_valid_response_without_exposing_key() -> None:
    provider = GPTImageProvider(endpoint="https://example.test/images", api_key="secret")
    result = provider.normalize_response(
        {
            "id": "provider-request-1",
            "model": "gpt-image-2",
            "data": [{"url": "https://assets.example.test/image-1.png"}],
            "usage": {"cost": 0.12},
        },
        latency_ms=321,
    )

    assert isinstance(result, GenerationResult)
    assert result.provider_request_id == "provider-request-1"
    assert result.model_name == "gpt-image-2"
    assert result.asset_urls == ["https://assets.example.test/image-1.png"]
    assert result.latency_ms == 321
    assert result.cost == 0.12
    assert "secret" not in repr(result)


def test_provider_rejects_malformed_response() -> None:
    provider = GPTImageProvider(endpoint="https://example.test/images", api_key="secret")

    with pytest.raises(ProviderResponseError, match="asset URL"):
        provider.normalize_response({"id": "request-1", "data": [{}]}, latency_ms=1)


def test_provider_request_payload_does_not_contain_credentials() -> None:
    provider = GPTImageProvider(endpoint="https://example.test/images", api_key="secret")
    payload = provider.build_payload(
        GenerationRequest(
            prompt="adult male portrait",
            output_count=2,
            aspect_ratio="1:1",
            strategy_version="strategy_v1",
        )
    )

    assert payload == {
        "model": "gpt-image-2",
        "prompt": "adult male portrait",
        "n": 2,
        "aspect_ratio": "1:1",
    }
    assert "api_key" not in payload
    assert "secret" not in repr(payload)
