import base64

import httpx
import pytest

from tevion_api.assets import AssetError, LocalAssetStore
from tevion_api.main import _asset_public_url


def test_persists_b64_image_as_long_lived_tevion_uri(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)
    uri = store.persist_b64(base64.b64encode(b"\x89PNG\r\nasset").decode(), "image/png")

    assert uri.startswith("tevion://assets/")
    assert store.read(uri) == b"\x89PNG\r\nasset"
    assert "data:" not in uri


def test_rejects_unsupported_mime_and_oversized_data(tmp_path) -> None:
    store = LocalAssetStore(tmp_path, max_bytes=4)

    with pytest.raises(AssetError, match="MIME"):
        store.persist_bytes(b"x", "text/plain")
    with pytest.raises(AssetError, match="size"):
        store.persist_bytes(b"12345", "image/png")


def test_download_does_not_follow_redirects(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    store = LocalAssetStore(tmp_path, http_client=client)

    with pytest.raises(AssetError, match="redirect"):
        store.persist_url("https://example.com/image.png")


def test_download_rejects_private_ssrf_target(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)

    with pytest.raises(AssetError, match="private"):
        store.persist_url("http://127.0.0.1/image.png")


def test_internal_asset_uri_is_exposed_only_through_owned_api_endpoint() -> None:
    assert _asset_public_url("tevion://assets/abc.png") == "/api/v1/assets/abc.png"
    assert _asset_public_url("https://provider.example/image.png") == "https://provider.example/image.png"
