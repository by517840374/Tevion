import pytest

from tevion_api.provider import ProviderError, classify_provider_error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("slow"), "timeout"),
        (ConnectionError("429 rate limit"), "rate_limit"),
        (RuntimeError("503 service unavailable"), "server_error"),
        (ValueError("malformed response"), "malformed_response"),
        (RuntimeError("model unavailable"), "model_unavailable"),
    ],
)
def test_provider_errors_are_normalized(error: Exception, code: str) -> None:
    normalized = classify_provider_error(error)

    assert isinstance(normalized, ProviderError)
    assert normalized.code == code
    assert normalized.retryable is (code in {"timeout", "rate_limit", "server_error"})
    assert normalized.message != str(error)


def test_provider_error_does_not_expose_credentials() -> None:
    normalized = classify_provider_error(RuntimeError("request failed with secret-key-123"))

    assert "secret-key-123" not in normalized.message
