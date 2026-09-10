import base64
import binascii
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Protocol

import httpx

DEFAULT_MAIZI_BASE_URL = "https://www.maizitech.ai/v1"
DEFAULT_PIXHUB_BASE_URL = "https://pixhub.top/v1"


class ProviderConfigError(ValueError):
    """Raised when a provider is not configured safely."""


class ProviderResponseError(ValueError):
    """Raised when a provider response cannot be normalized."""


class ProviderOperationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderError:
    code: str
    message: str
    retryable: bool


def classify_provider_error(error: Exception) -> ProviderError:
    raw = str(error)
    lowered = raw.lower()
    if isinstance(error, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return ProviderError("timeout", "provider request timed out", True)
    if "429" in lowered or "rate limit" in lowered:
        return ProviderError("rate_limit", "provider rate limit reached", True)
    if any(token in lowered for token in ("500", "502", "503", "504", "server error")):
        return ProviderError("server_error", "provider server error", True)
    if "model" in lowered and "unavailable" in lowered:
        return ProviderError("model_unavailable", "requested model is unavailable", False)
    if "malformed" in lowered or any(phrase in lowered for phrase in ("missing", "no asset", "no result", "cost is")):
        return ProviderError("malformed_response", "provider response is malformed", False)
    return ProviderError("provider_error", "provider request failed", False)


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    output_count: int = 1
    aspect_ratio: str = "1:1"
    strategy_version: str = "default"
    quality: str = "low"


@dataclass(frozen=True)
class GenerationResult:
    provider_name: str
    provider_request_id: str
    model_name: str
    asset_urls: list[str]
    latency_ms: int
    metadata_source: str
    cost: float | None = None
    metadata: dict[str, Any] | None = None
    requested_count: int = 1
    actual_count: int | None = None
    completeness: str | None = None
    shortfall: int | None = None
    asset_mime_types: list[str] | None = None

    def __post_init__(self) -> None:
        actual_count = len(self.asset_urls) if self.actual_count is None else self.actual_count
        shortfall = max(self.requested_count - actual_count, 0) if self.shortfall is None else self.shortfall
        completeness = self.completeness
        if completeness is None:
            completeness = (
                "complete" if actual_count == self.requested_count else "partial" if actual_count else "empty"
            )
        object.__setattr__(self, "actual_count", actual_count)
        object.__setattr__(self, "shortfall", shortfall)
        object.__setattr__(self, "completeness", completeness)


@dataclass(frozen=True)
class ProviderOperationResult:
    status: ProviderOperationStatus
    provider_request_id: str | None
    result: GenerationResult | None = None
    error_code: str | None = None
    error_message: str | None = None


class GPTImageProvider:
    """Provider boundary for GPT Image 2-compatible image generation APIs."""

    model_name = "gpt-image-2"

    def __init__(self, *, endpoint: str, api_key: str, model_name: str | None = None) -> None:
        if not endpoint.strip():
            raise ProviderConfigError("provider endpoint is required")
        if not api_key.strip():
            raise ProviderConfigError("provider API key is required")
        self.endpoint = endpoint
        self._api_key = api_key
        if model_name:
            self.model_name = model_name

    def build_payload(self, request: GenerationRequest) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "prompt": request.prompt,
            "n": request.output_count,
            "aspect_ratio": request.aspect_ratio,
        }

    def normalize_response(
        self, response: dict[str, Any], *, latency_ms: int, requested_count: int = 1
    ) -> GenerationResult:
        request_id = response.get("id")
        data = response.get("data")
        if not isinstance(request_id, str) or not request_id:
            raise ProviderResponseError("provider request id is missing")
        if not isinstance(data, list) or not data:
            raise ProviderResponseError("provider response data is missing")

        asset_urls: list[str] = []
        asset_mime_types: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url:
                asset_urls.append(url)
                asset_mime_types.append("image/png")
                continue
            encoded = item.get("b64_json")
            if not isinstance(encoded, str) or not encoded:
                continue
            try:
                base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ProviderResponseError("provider base64 asset is invalid") from exc
            asset_urls.append(f"data:image/png;base64,{encoded}")
            asset_mime_types.append("image/png")
        if not asset_urls:
            raise ProviderResponseError("provider response contains no asset URL")

        usage = response.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if cost is not None and not isinstance(cost, (int, float)):
            raise ProviderResponseError("provider cost is malformed")

        return GenerationResult(
            provider_name="gpt-image",
            provider_request_id=request_id,
            model_name=response.get("model", self.model_name),
            asset_urls=asset_urls,
            latency_ms=latency_ms,
            metadata_source="provider_response",
            cost=float(cost) if cost is not None else None,
            metadata={"strategy_version": response.get("strategy_version")}
            if response.get("strategy_version")
            else None,
            requested_count=requested_count,
            asset_mime_types=asset_mime_types,
        )


class PixhubImageProvider:
    """Synchronous OpenAI-compatible Pixhub image generation adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_PIXHUB_BASE_URL,
        model_name: str = "gpt-image-2.5",
        response_format: str = "url",
        quality: str = "low",
        default_size: str = "1024x1024",
        timeout_seconds: float = 180.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ProviderConfigError("Pixhub API key is required")
        if not base_url.strip():
            raise ProviderConfigError("Pixhub endpoint is required")
        if response_format not in {"url", "b64_json"}:
            raise ProviderConfigError("Pixhub response format must be url or b64_json")
        if not default_size.strip():
            raise ProviderConfigError("Pixhub default size is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.response_format = response_format
        self.quality = quality
        self.default_size = default_size
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None

    @property
    def provider_name(self) -> str:
        return "pixhub"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def build_payload(self, request: GenerationRequest) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "prompt": request.prompt,
            "n": 1,
            "size": self.default_size,
            "quality": request.quality or self.quality,
            "response_format": self.response_format,
        }

    def normalize_response(
        self, response: dict[str, Any], *, latency_ms: int, requested_count: int = 1
    ) -> GenerationResult:
        request_id = response.get("id")
        data = response.get("data")
        if not isinstance(request_id, str) or not request_id:
            raise ProviderResponseError("Pixhub request id is missing")
        if not isinstance(data, list) or not data:
            raise ProviderResponseError("Pixhub response data is missing")
        asset_urls: list[str] = []
        persistence: str | None = None
        for item in data:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("url"), str) and item["url"]:
                asset_urls.append(item["url"])
                persistence = "temporary_provider_url"
            elif isinstance(item.get("b64_json"), str) and item["b64_json"]:
                asset_urls.append(f"data:image/png;base64,{item['b64_json']}")
                persistence = "temporary_base64"
        if not asset_urls:
            raise ProviderResponseError("Pixhub response contains no asset")
        return GenerationResult(
            provider_name=self.provider_name,
            provider_request_id=request_id,
            model_name=response.get("model") or self.model_name,
            asset_urls=asset_urls,
            latency_ms=latency_ms,
            metadata_source="provider_response",
            metadata={"asset_persistence": persistence},
            requested_count=requested_count,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        import time

        started = time.monotonic()
        try:
            response = self._client.post(
                f"{self.base_url}/images/generations", headers=self._headers(), json=self.build_payload(request)
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as error:
            raise ProviderResponseError(f"Pixhub request failed with HTTP {error.response.status_code}") from None
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise ProviderResponseError(f"Pixhub request failed: {self._redact(str(error))}") from None
        if not isinstance(body, dict):
            raise ProviderResponseError("Pixhub response is malformed")
        return self.normalize_response(
            body, latency_ms=int((time.monotonic() - started) * 1000), requested_count=request.output_count
        )

    @staticmethod
    def _edit_filename(mime_type: str) -> str:
        suffixes = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
        normalized = mime_type.split(";", 1)[0].strip().lower()
        if normalized not in suffixes:
            raise ProviderConfigError("unsupported parent image MIME type")
        return f"parent.{suffixes[normalized]}"

    def normalize_edit_response(
        self,
        response: dict[str, Any],
        *,
        latency_ms: int,
        parent_image_id: str,
        parent_run_id: str,
        owner_id: str,
    ) -> GenerationResult:
        result = self.normalize_response(response, latency_ms=latency_ms, requested_count=1)
        metadata = {
            **(result.metadata or {}),
            "operation": "image_to_image",
            "parent_image_id": parent_image_id,
            "parent_run_id": parent_run_id,
            "owner_id": owner_id,
        }
        return replace(result, metadata=metadata, requested_count=1)

    def edit_image(
        self,
        *,
        prompt: str,
        image: bytes,
        mime_type: str,
        parent_image_id: str,
        parent_run_id: str,
        owner_id: str,
    ) -> GenerationResult:
        """Edit exactly one owned parent asset through Pixhub's multipart endpoint.

        Ownership and lineage identifiers are accepted as an explicit boundary
        contract; the asset bytes are the only parent input sent to Pixhub.
        Persistence and ImageVersion wiring remain outside this provider slice.
        """
        if not parent_image_id.strip():
            raise ProviderConfigError("parent image id is required")
        if not parent_run_id.strip():
            raise ProviderConfigError("parent run id is required")
        if not owner_id.strip():
            raise ProviderConfigError("owner id is required")
        if not image:
            raise ProviderConfigError("parent image is required")
        filename = self._edit_filename(mime_type)
        normalized_mime = mime_type.split(";", 1)[0].strip().lower()
        started = __import__("time").monotonic()
        try:
            response = self._client.post(
                f"{self.base_url}/images/edits",
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={
                    "model": self.model_name,
                    "prompt": prompt,
                    "n": "1",
                    "size": self.default_size,
                    "quality": self.quality,
                    "response_format": self.response_format,
                },
                files={"image": (filename, image, normalized_mime)},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as error:
            raise ProviderResponseError(f"Pixhub edit request failed with HTTP {error.response.status_code}") from None
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise ProviderResponseError(f"Pixhub edit request failed: {self._redact(str(error))}") from None
        if not isinstance(body, dict):
            raise ProviderResponseError("Pixhub edit response is malformed")
        return self.normalize_edit_response(
            body,
            latency_ms=int((__import__("time").monotonic() - started) * 1000),
            parent_image_id=parent_image_id,
            parent_run_id=parent_run_id,
            owner_id=owner_id,
        )

    def _redact(self, message: str) -> str:
        return message.replace(self._api_key, "[REDACTED]")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class ImageGenerationProvider(Protocol):
    """Structural contract: any provider able to execute a generation request."""

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class MaizitechImageProvider:
    """Real HTTP provider for a GPT-image-2 compatible async API (maizitech.ai).

    Flow: POST /images/generations -> {task_id, status: pending}, then poll
    GET /tasks/{task_id} until completed, and normalize result_urls into the
    internal GenerationResult. Credentials come from the environment only.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_MAIZI_BASE_URL,
        model_name: str = "gpt-image-2",
        http_client: httpx.Client | None = None,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 180.0,
    ) -> None:
        if not api_key.strip():
            raise ProviderConfigError("Maizitech API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._client = http_client or httpx.Client(timeout=httpx.Timeout(30.0))
        self._owns_client = http_client is None
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "maizitech"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _submit(self, request: GenerationRequest) -> tuple[str, list[dict[str, Any]]]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": request.prompt,
            "size": request.aspect_ratio,
            "quality": request.quality,
        }
        if request.output_count > 1:
            payload["n"] = request.output_count
        response = self._client.post(f"{self.base_url}/images/generations", headers=self._headers(), json=payload)
        response.raise_for_status()
        body = response.json()
        items = body.get("data") or []
        if items and isinstance(items[0], dict) and items[0].get("url"):
            # synchronous-style response with immediate URL
            return "", [item for item in items if isinstance(item, dict)]
        task_id = items[0].get("task_id") if items else None
        if not isinstance(task_id, str) or not task_id:
            raise ProviderResponseError("provider returned no task id")
        return task_id, []

    def submit(self, request: GenerationRequest) -> ProviderOperationResult:
        """Submit exactly once and return the provider ID before polling."""
        try:
            task_id, immediate_items = self._submit(request)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            return ProviderOperationResult(
                ProviderOperationStatus.UNKNOWN,
                None,
                error_code="submit_unknown",
                error_message=self._redact(str(error)),
            )
        if not task_id:
            result = GenerationResult(
                provider_name=self.provider_name,
                provider_request_id="",
                model_name=self.model_name,
                asset_urls=[item["url"] for item in immediate_items if item.get("url")],
                latency_ms=0,
                metadata_source="provider_response",
                requested_count=request.output_count,
            )
            return ProviderOperationResult(ProviderOperationStatus.COMPLETED, None, result=result)
        return ProviderOperationResult(ProviderOperationStatus.PENDING, task_id)

    def _redact(self, message: str) -> str:
        return message.replace(self.api_key, "[REDACTED]")

    def _safe_metadata(self, body: dict[str, Any]) -> dict[str, Any]:
        params = body.get("params")
        safe_params = (
            {
                key: value
                for key, value in params.items()
                if key in {"size", "quality"} and isinstance(value, (str, int, float, bool))
            }
            if isinstance(params, dict)
            else None
        )
        metadata: dict[str, Any] = {"provider": self.provider_name}
        if safe_params:
            metadata["params"] = safe_params
            if isinstance(safe_params.get("size"), str):
                metadata["size"] = safe_params["size"]
        return metadata

    def _poll(self, task_id: str) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = self._client.get(f"{self.base_url}/tasks/{task_id}", headers=self._headers())
            response.raise_for_status()
            body = response.json()
            status = (body.get("status") or "").lower()
            if status == "completed":
                return body
            if status in {"failed", "error", "cancelled"}:
                raise ProviderResponseError(self._redact(f"provider task failed: {body.get('error_msg') or status}"))
            time.sleep(self.poll_interval_seconds)
        raise ProviderResponseError("provider task timed out")

    def _result_from_body(
        self, task_id: str, body: dict[str, Any], *, requested_count: int = 1
    ) -> ProviderOperationResult:
        status = (body.get("status") or "").lower()
        if status == "completed":
            urls = body.get("result_urls") or []
            if not urls:
                return ProviderOperationResult(
                    ProviderOperationStatus.FAILED,
                    task_id,
                    error_code="malformed_response",
                    error_message="completed task has no result URLs",
                )
            result = GenerationResult(
                provider_name=self.provider_name,
                provider_request_id=task_id,
                model_name=body.get("model") or self.model_name,
                asset_urls=[url for url in urls if isinstance(url, str)],
                latency_ms=0,
                metadata_source="provider_response",
                cost=float(body["cost"]) if body.get("cost") is not None else None,
                metadata=self._safe_metadata(body),
                requested_count=requested_count,
            )
            return ProviderOperationResult(ProviderOperationStatus.COMPLETED, task_id, result=result)
        if status in {"failed", "error", "cancelled"}:
            return ProviderOperationResult(
                ProviderOperationStatus.FAILED,
                task_id,
                error_code="provider_failed",
                error_message=self._redact(str(body.get("error_msg") or status)),
            )
        return ProviderOperationResult(ProviderOperationStatus.PENDING, task_id)

    def _query(self, task_id: str, *, requested_count: int = 1) -> ProviderOperationResult:
        response = self._client.get(f"{self.base_url}/tasks/{task_id}", headers=self._headers())
        response.raise_for_status()
        return self._result_from_body(task_id, response.json(), requested_count=requested_count)

    def poll(self, provider_request_id: str, *, requested_count: int = 1) -> ProviderOperationResult:
        """Poll an existing request, retaining its ID on transport uncertainty."""
        import time

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                outcome = self._query(provider_request_id, requested_count=requested_count)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                return ProviderOperationResult(
                    ProviderOperationStatus.UNKNOWN,
                    provider_request_id,
                    error_code="poll_unknown",
                    error_message=self._redact(str(error)),
                )
            if outcome.status is not ProviderOperationStatus.PENDING:
                return outcome
            time.sleep(self.poll_interval_seconds)
        return ProviderOperationResult(
            ProviderOperationStatus.UNKNOWN,
            provider_request_id,
            error_code="poll_timeout",
            error_message="provider task polling timed out",
        )

    def resume(self, provider_request_id: str, *, requested_count: int = 1) -> ProviderOperationResult:
        """Recover by querying a persisted ID; this method never submits."""
        try:
            return self._query(provider_request_id, requested_count=requested_count)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            return ProviderOperationResult(
                ProviderOperationStatus.UNKNOWN,
                provider_request_id,
                error_code="resume_unknown",
                error_message=self._redact(str(error)),
            )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        import time

        started = time.monotonic()
        task_id, immediate_items = self._submit(request)
        latency_ms = int((time.monotonic() - started) * 1000)
        if task_id == "":
            urls = [item["url"] for item in immediate_items if item.get("url")]
            return GenerationResult(
                provider_name=self.provider_name,
                provider_request_id="",
                model_name=self.model_name,
                asset_urls=urls,
                latency_ms=latency_ms,
                metadata_source="provider_response",
                cost=None,
                metadata=None,
                requested_count=request.output_count,
            )
        body = self._poll(task_id)
        latency_ms = int((time.monotonic() - started) * 1000)
        urls = body.get("result_urls") or []
        if not urls:
            raise ProviderResponseError("completed task has no result URLs")
        return GenerationResult(
            provider_name=self.provider_name,
            provider_request_id=task_id,
            model_name=body.get("model") or self.model_name,
            asset_urls=[url for url in urls if isinstance(url, str)],
            latency_ms=latency_ms,
            metadata_source="provider_response",
            cost=float(body["cost"]) if body.get("cost") is not None else None,
            metadata=self._safe_metadata(body),
            requested_count=request.output_count,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "GPTImageProvider",
    "PixhubImageProvider",
    "ImageGenerationProvider",
    "MaizitechImageProvider",
    "ProviderConfigError",
    "ProviderResponseError",
    "ProviderOperationStatus",
    "ProviderOperationResult",
    "ProviderError",
    "classify_provider_error",
    "DEFAULT_MAIZI_BASE_URL",
    "DEFAULT_PIXHUB_BASE_URL",
]
