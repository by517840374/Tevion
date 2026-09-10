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


def test_pixhub_edit_image_posts_one_parent_multipart_and_preserves_lineage_contract():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={"id": "edit-123", "model": "gpt-image-2.5", "data": [{"url": "https://tmp.test/refined.png"}]},
        )

    result = _provider(handler).edit_image(
        prompt="make the lighting warmer",
        image=b"fake-png",
        mime_type="image/png",
        parent_image_id="image_parent",
        parent_run_id="run_parent",
        owner_id="user_owner",
    )

    assert seen["url"] == "https://pixhub.example.test/v1/images/edits"
    assert "multipart/form-data" in seen["headers"]["content-type"]
    assert b'name="image"' in seen["body"]
    assert b'filename="parent.png"' in seen["body"]
    assert b"Content-Type: image/png" in seen["body"]
    assert b"fake-png" in seen["body"]
    assert b'name="n"' in seen["body"] and b"\r\n1\r\n" in seen["body"]
    assert b'name="prompt"' in seen["body"]
    assert b"parent_image_id" not in seen["body"]
    assert result.asset_urls == ["https://tmp.test/refined.png"]
    assert result.metadata == {
        "asset_persistence": "temporary_provider_url",
        "operation": "image_to_image",
        "parent_image_id": "image_parent",
        "parent_run_id": "run_parent",
        "owner_id": "user_owner",
    }


def test_pixhub_edit_image_rejects_invalid_parent_contract_and_mime():
    provider = PixhubImageProvider(api_key=API_KEY, base_url="https://pixhub.test/v1")

    with pytest.raises(ProviderConfigError, match="parent image"):
        provider.edit_image(
            prompt="x", image=b"x", mime_type="image/png", parent_image_id="", parent_run_id="r", owner_id="u"
        )
    with pytest.raises(ProviderConfigError, match="parent run"):
        provider.edit_image(
            prompt="x", image=b"x", mime_type="image/png", parent_image_id="i", parent_run_id="", owner_id="u"
        )
    with pytest.raises(ProviderConfigError, match="owner"):
        provider.edit_image(
            prompt="x", image=b"x", mime_type="image/png", parent_image_id="i", parent_run_id="r", owner_id=""
        )
    with pytest.raises(ProviderConfigError, match="MIME"):
        provider.edit_image(
            prompt="x", image=b"x", mime_type="application/pdf", parent_image_id="i", parent_run_id="r", owner_id="u"
        )


def test_pixhub_edit_image_normalizes_b64_response_with_mime():
    provider = PixhubImageProvider(api_key=API_KEY, base_url="https://pixhub.test/v1")

    result = provider.normalize_edit_response(
        {"id": "edit-b64", "data": [{"b64_json": "ZmFrZQ=="}]},
        latency_ms=3,
        parent_image_id="image_parent",
        parent_run_id="run_parent",
        owner_id="user_owner",
    )

    assert result.asset_urls == ["data:image/png;base64,ZmFrZQ=="]
    assert result.metadata["operation"] == "image_to_image"
