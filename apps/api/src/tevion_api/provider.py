from dataclasses import dataclass
from typing import Any


class ProviderConfigError(ValueError):
    """Raised when a provider is not configured safely."""


class ProviderResponseError(ValueError):
    """Raised when a provider response cannot be normalized."""


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    output_count: int = 1
    aspect_ratio: str = "1:1"
    strategy_version: str = "default"


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


__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "GPTImageProvider",
    "ProviderConfigError",
    "ProviderResponseError",
]


ImageGenerationProvider = GPTImageProvider
