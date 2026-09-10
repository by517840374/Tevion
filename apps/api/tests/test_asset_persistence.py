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


def test_read_source_downloads_historical_https_once_and_returns_validated_bytes(tmp_path, monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"historical-png")

    monkeypatch.setattr(LocalAssetStore, "_reject_private_host", staticmethod(lambda hostname: None))
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    store = LocalAssetStore(tmp_path, http_client=client)

    data, mime_type = store.read_source("https://history.example/image.png")

    assert (data, mime_type) == (b"historical-png", "image/png")
    assert calls == 1
    assert not list(tmp_path.iterdir())


def test_read_source_rejects_historical_redirect(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(LocalAssetStore, "_reject_private_host", staticmethod(lambda hostname: None))
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "https://private.example/image.png"})
        ),
        follow_redirects=False,
    )
    store = LocalAssetStore(tmp_path, http_client=client)

    with pytest.raises(AssetError, match="redirect"):
        store.read_source("https://history.example/image.png")


def test_read_source_rejects_private_historical_host(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)

    with pytest.raises(AssetError, match="private"):
        store.read_source("https://127.0.0.1/image.png")


def test_internal_asset_uri_is_exposed_only_through_owned_api_endpoint() -> None:
    assert _asset_public_url("tevion://assets/abc.png") == "/api/v1/assets/abc.png"
    assert _asset_public_url("https://provider.example/image.png") == "https://provider.example/image.png"
