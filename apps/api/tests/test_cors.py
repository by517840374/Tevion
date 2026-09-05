from fastapi import FastAPI
from fastapi.testclient import TestClient

from tevion_api.cors import configure_cors, get_cors_settings


def _app_with_cors() -> FastAPI:
    app = FastAPI()
    configure_cors(app)

    @app.get("/resource")
    def resource() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_local_defaults_allow_common_frontend_origins(monkeypatch) -> None:
    monkeypatch.delenv("TEVION_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("TEVION_ENVIRONMENT", raising=False)

    settings = get_cors_settings()

    assert settings.environment == "local"
    assert "http://localhost:3000" in settings.allowed_origins
    assert "http://127.0.0.1:5173" in settings.allowed_origins
    assert settings.allow_credentials is False


def test_production_without_origins_is_safe_and_readable(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TEVION_ENVIRONMENT", "production")
    monkeypatch.delenv("TEVION_CORS_ALLOWED_ORIGINS", raising=False)

    settings = get_cors_settings()

    assert settings.allowed_origins == []
    assert "TEVION_CORS_ALLOWED_ORIGINS" in caplog.text


def test_cors_values_are_configurable_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "TEVION_CORS_ALLOWED_ORIGINS",
        "https://app.example.test, https://admin.example.test",
    )
    monkeypatch.setenv("TEVION_CORS_ALLOWED_METHODS", "GET, POST, OPTIONS")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_HEADERS", "Authorization, Content-Type, X-Request-ID")

    settings = get_cors_settings()

    assert settings.allowed_origins == [
        "https://app.example.test",
        "https://admin.example.test",
    ]
    assert settings.allowed_methods == ["GET", "POST", "OPTIONS"]
    assert settings.allowed_headers == ["Authorization", "Content-Type", "X-Request-ID"]


def test_allowed_origin_supports_bearer_preflight_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ENVIRONMENT", "production")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_ORIGINS", "https://app.example.test")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_METHODS", "GET, POST, OPTIONS")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_HEADERS", "Authorization, Content-Type")

    client = TestClient(_app_with_cors())
    response = client.options(
        "/resource",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.test"
    assert "access-control-allow-credentials" not in response.headers
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_disallowed_origin_has_no_cors_permission(monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ENVIRONMENT", "production")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_ORIGINS", "https://app.example.test")

    response = TestClient(_app_with_cors()).get("/resource", headers={"Origin": "https://evil.example.test"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_blank_production_origin_configuration_does_not_enable_wildcard(monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ENVIRONMENT", "production")
    monkeypatch.setenv("TEVION_CORS_ALLOWED_ORIGINS", "")

    settings = get_cors_settings()

    assert settings.allowed_origins == []
    assert "*" not in settings.allowed_origins
