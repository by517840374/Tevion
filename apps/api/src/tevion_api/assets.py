"""Bounded persistence for provider image payloads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

ALLOWED_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class AssetError(ValueError):
    """Raised when an asset cannot be safely persisted or read."""


class LocalAssetStore:
    """Small content-addressed store; returned URIs never expire with a provider URL."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_bytes: int = 10 * 1024 * 1024,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.timeout = timeout
        self._client = http_client or httpx.Client(timeout=timeout, follow_redirects=False)
        self._owns_client = http_client is None

    def persist_b64(self, value: str, mime_type: str) -> str:
        if value.startswith("data:"):
            header, separator, value = value.partition(",")
            if not separator or ";base64" not in header:
                raise AssetError("invalid base64 data URI")
            mime_type = header[5:].split(";", 1)[0]
        try:
            data = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AssetError("invalid base64 image") from exc
        return self.persist_bytes(data, mime_type)

    def persist_bytes(self, data: bytes, mime_type: str) -> str:
        mime_type = mime_type.split(";", 1)[0].strip().lower()
        if mime_type not in ALLOWED_MIME_TYPES:
            raise AssetError("unsupported MIME type")
        if not data:
            raise AssetError("asset is empty")
        if len(data) > self.max_bytes:
            raise AssetError("asset exceeds maximum size")
        digest = hashlib.sha256(data).hexdigest()
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime_type]
        key = f"{digest}.{suffix}"
        path = self.root / key
        self.root.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=f".{key}.", delete=False) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            try:
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return f"tevion://assets/{key}"

    def persist_upload(self, data: bytes, mime_type: str) -> str:
        """Persist a user upload after checking declared and actual format."""
        normalized = mime_type.split(";", 1)[0].strip().lower()
        if not _matches_image_signature(data, normalized):
            raise AssetError("uploaded content is not a valid image")
        return self.persist_bytes(data, normalized)

    def persist_url(self, url: str) -> str:
        data, mime_type = self.read_source(url)
        return self.persist_bytes(data, mime_type)

    def read_source(self, url: str) -> tuple[bytes, str]:
        """Download one historical HTTP(S) asset with the store's safety checks."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AssetError("asset URL must use HTTP(S)")
        self._reject_private_host(parsed.hostname)
        try:
            response = self._client.get(url, timeout=self.timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise AssetError("asset download failed") from exc
        if 300 <= response.status_code < 400:
            raise AssetError("asset download redirect is not allowed")
        if response.status_code != 200:
            raise AssetError("asset download returned an error")
        mime_type = response.headers.get("content-type", "").split(";", 1)[0]
        if len(response.content) > self.max_bytes:
            raise AssetError("asset exceeds maximum size")
        normalized_mime = mime_type.strip().lower()
        if normalized_mime not in ALLOWED_MIME_TYPES:
            raise AssetError("unsupported MIME type")
        if not response.content:
            raise AssetError("asset is empty")
        return response.content, normalized_mime

    def persist_source(self, value: str, mime_type: str | None = None) -> str:
        if value.startswith("data:"):
            return self.persist_b64(value, mime_type or "")
        if value.startswith(("http://", "https://")):
            return self.persist_url(value)
        raise AssetError("unsupported asset source")

    def read(self, uri: str) -> bytes:
        prefix = "tevion://assets/"
        if not uri.startswith(prefix):
            if uri.startswith(("http://", "https://")):
                raise AssetError("historical HTTP assets require a source download")
            raise AssetError("unsupported asset URI")
        key = uri[len(prefix) :]
        if not key or Path(key).name != key or key != Path(key).name:
            raise AssetError("invalid asset key")
        path = self.root / key
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise AssetError("asset not found") from exc

    @staticmethod
    def _reject_private_host(hostname: str) -> None:
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise AssetError("asset host could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise AssetError("asset URL targets a private network")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class ObjectStorageAssetStore(LocalAssetStore):
    """Persist validated images through the configured ysqvr object-storage API."""

    def __init__(
        self,
        *,
        upload_url: str,
        presign_url: str,
        api_key: str,
        folder: str = "images",
        max_bytes: int = 10 * 1024 * 1024,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not upload_url.startswith("https://") or not presign_url.startswith("https://"):
            raise ValueError("object storage endpoints must use HTTPS")
        if not api_key.strip():
            raise ValueError("object storage API key is required")
        super().__init__("/tmp/tevion-assets", max_bytes=max_bytes, timeout=timeout, http_client=http_client)
        self.upload_url, self.presign_url, self.api_key, self.folder = upload_url, presign_url, api_key, folder

    def persist_bytes(self, data: bytes, mime_type: str) -> str:
        normalized = mime_type.split(";", 1)[0].strip().lower()
        if normalized not in ALLOWED_MIME_TYPES:
            raise AssetError("unsupported MIME type")
        if not data:
            raise AssetError("asset is empty")
        if len(data) > self.max_bytes:
            raise AssetError("asset exceeds maximum size")
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[normalized]
        try:
            response = self._client.post(
                self.upload_url,
                headers={"X-API-Key": self.api_key},
                data={"folder": self.folder},
                files={"file": (f"image.{suffix}", data, normalized)},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AssetError("object storage upload failed") from exc
        if not payload.get("success") or not payload.get("key") or not payload.get("bucket"):
            raise AssetError("object storage returned an invalid upload response")
        return f"s3://{payload['bucket']}/{payload['key']}"

    def public_url(self, uri: str) -> str:
        _, key = self._parse_uri(uri)
        try:
            response = self._client.get(
                self.presign_url, params={"key": key}, headers={"X-API-Key": self.api_key}, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AssetError("object storage presign failed") from exc
        url = payload.get("url") or payload.get("download_url") or payload.get("presigned_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise AssetError("object storage returned an invalid presign response")
        return url

    def read(self, uri: str) -> bytes:
        if uri.startswith("s3://"):
            data, _ = self.read_source(self.public_url(uri))
            return data
        return super().read(uri)

    @staticmethod
    def _parse_uri(uri: str) -> tuple[str, str]:
        if not uri.startswith("s3://"):
            raise AssetError("unsupported object storage URI")
        bucket, separator, key = uri[5:].partition("/")
        if not separator or not bucket or not key or ".." in key.split("/"):
            raise AssetError("invalid object storage URI")
        return bucket, key


def _matches_image_signature(data: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def build_asset_store() -> LocalAssetStore:
    api_key = os.environ.get("TEVION_STORAGE_API_KEY", "").strip()
    if not api_key:
        return LocalAssetStore(os.environ.get("TEVION_ASSET_ROOT", "/tmp/tevion-assets"))
    return ObjectStorageAssetStore(
        upload_url=os.environ.get("TEVION_STORAGE_UPLOAD_URL", "https://ysqvr.com/api/storage/upload"),
        presign_url=os.environ.get("TEVION_STORAGE_PRESIGN_URL", "https://ysqvr.com/api/storage/presign"),
        api_key=api_key,
        folder=os.environ.get("TEVION_STORAGE_FOLDER", "images"),
    )
