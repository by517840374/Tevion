# Provider Contract

Source: `apps/api/src/tevion_api/provider.py` and `apps/api/tests/test_provider.py`.

## Boundary

`ImageGenerationProvider` is currently an alias of `GPTImageProvider`.

The provider boundary is responsible for:

- building a request payload from a generation request;
- validating provider configuration;
- normalizing provider responses into internal results;
- classifying provider failures into stable error codes.

## GenerationRequest

Dataclass fields:

- `prompt: str`
- `output_count: int = 1`
- `aspect_ratio: str = "1:1"`
- `strategy_version: str = "default"`

Used by `build_payload()`.

Current payload mapping:

- `model` ← provider `model_name`
- `prompt` ← request prompt
- `n` ← request output_count
- `aspect_ratio` ← request aspect_ratio

## GenerationResult

Dataclass fields:

- `provider_request_id: str`
- `model_name: str`
- `asset_urls: list[str]`
- `latency_ms: int`
- `cost: float | None = None`
- `metadata: dict[str, Any] | None = None`

Normalized from provider responses with:

- `id` as request id
- `data[*].url` as asset URLs
- `usage.cost` as optional cost
- `strategy_version` copied into metadata when present

## Error codes

`classify_provider_error()` maps failures to:

- `timeout` → retryable
- `rate_limit` → retryable
- `server_error` → retryable
- `model_unavailable` → not retryable
- `malformed_response` → not retryable
- `provider_error` → not retryable fallback

## Secret boundary

- `endpoint` and `api_key` are required at init time.
- Empty endpoint or empty API key raises `ProviderConfigError`.
- `build_payload()` does not include credentials.
- Normalized results and payloads used in tests do not expose the secret value.

## Real endpoint integration placeholder

Current code only defines the boundary; it does not call a live endpoint here.

To wire a real endpoint later:

1. supply a non-empty HTTPS endpoint and API key to `GPTImageProvider`;
2. send the `build_payload()` output to the provider endpoint;
3. parse the raw response into the `normalize_response()` shape;
4. convert provider exceptions through `classify_provider_error()`;
5. keep credentials out of logs, payloads, and result objects.
