from dataclasses import dataclass
from typing import Any, Protocol

import httpx

DEFAULT_MAIZI_BASE_URL = "https://www.maizitech.ai/v1"


class ProviderConfigError(ValueError):
    """Raised when a provider is not configured safely."""


class ProviderResponseError(ValueError):
    """Raised when a provider response cannot be normalized."""


@dataclass(frozen=True)
class ProviderError:
    code: str
    message: str
    retryable: bool


def classify_provider_error(error: Exception) -> ProviderError:
    raw = str(error)
    lowered = raw.lower()
    if isinstance(error, TimeoutError) or "timeout" in lowered:
        return ProviderError("timeout", "provider request timed out", True)
    if "429" in lowered or "rate limit" in lowered:
        return ProviderError("rate_limit", "provider rate limit reached", True)
    if any(token in lowered for token in ("500", "502", "503", "504", "server error")):
        return ProviderError("server_error", "provider server error", True)
    if "model" in lowered and "unavailable" in lowered:
        return ProviderError("model_unavailable", "requested model is unavailable", False)
    if "malformed" in lowered or isinstance(error, ValueError):
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
    provider_request_id: str
    model_name: str
    asset_urls: list[str]
    latency_ms: int
    cost: float | None = None
    metadata: dict[str, Any] | None = None


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

    def normalize_response(self, response: dict[str, Any], *, latency_ms: int) -> GenerationResult:
        request_id = response.get("id")
        data = response.get("data")
        if not isinstance(request_id, str) or not request_id:
            raise ProviderResponseError("provider request id is missing")
        if not isinstance(data, list) or not data:
            raise ProviderResponseError("provider response data is missing")

        asset_urls = [
            item["url"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]
        ]
        if not asset_urls:
            raise ProviderResponseError("provider response contains no asset URL")

        usage = response.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if cost is not None and not isinstance(cost, (int, float)):
            raise ProviderResponseError("provider cost is malformed")

        return GenerationResult(
            provider_request_id=request_id,
            model_name=response.get("model", self.model_name),
            asset_urls=asset_urls,
            latency_ms=latency_ms,
            cost=float(cost) if cost is not None else None,
            metadata={"strategy_version": response.get("strategy_version")}
            if response.get("strategy_version")
            else None,
        )


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

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _submit(self, request: GenerationRequest) -> str:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "prompt": request.prompt,
            "size": request.aspect_ratio,
            "quality": request.quality,
        }
        if request.output_count > 1:
            payload["n"] = request.output_count
        response = self._client.post(
            f"{self.base_url}/images/generations", headers=self._headers(), json=payload
        )
        response.raise_for_status()
        body = response.json()
        items = body.get("data") or []
        if items and isinstance(items[0], dict) and items[0].get("url"):
            # synchronous-style response with immediate URL
            self._immediate = items
            return ""
        task_id = items[0].get("task_id") if items else None
        if not isinstance(task_id, str) or not task_id:
            raise ProviderResponseError("provider returned no task id")
        return task_id

    def _redact(self, message: str) -> str:
        return message.replace(self.api_key, "[REDACTED]")

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
                raise ProviderResponseError(
                    self._redact(f"provider task failed: {body.get('error_msg') or status}")
                )
            time.sleep(self.poll_interval_seconds)
        raise ProviderResponseError("provider task timed out")

    def generate(self, request: GenerationRequest) -> GenerationResult:
        import time

        started = time.monotonic()
        task_id = self._submit(request)
        latency_ms = int((time.monotonic() - started) * 1000)
        if task_id == "":
            items = getattr(self, "_immediate", [])
            urls = [item["url"] for item in items if item.get("url")]
            return GenerationResult(
                provider_request_id="",
                model_name=self.model_name,
                asset_urls=urls,
                latency_ms=latency_ms,
                cost=None,
            )
        body = self._poll(task_id)
        latency_ms = int((time.monotonic() - started) * 1000)
        urls = body.get("result_urls") or []
        if not urls:
            raise ProviderResponseError("completed task has no result URLs")
        return GenerationResult(
            provider_request_id=task_id,
            model_name=body.get("model") or self.model_name,
            asset_urls=[url for url in urls if isinstance(url, str)],
            latency_ms=latency_ms,
            cost=float(body["cost"]) if body.get("cost") is not None else None,
            metadata={
                "provider": "maizitech",
                "params": body.get("params"),
                "size": (body.get("params") or {}).get("size"),
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "GPTImageProvider",
    "ImageGenerationProvider",
    "MaizitechImageProvider",
    "ProviderConfigError",
    "ProviderResponseError",
    "ProviderError",
    "classify_provider_error",
    "DEFAULT_MAIZI_BASE_URL",
]
