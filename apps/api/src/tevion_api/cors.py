"""Environment-driven CORS policy for the API.

Bearer tokens are sent explicitly in the Authorization header, so browser
credential cookies are not needed and ``allow_credentials`` remains false.
"""

import logging
import os
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

_ENVIRONMENT = "TEVION_ENVIRONMENT"
_ALLOWED_ORIGINS = "TEVION_CORS_ALLOWED_ORIGINS"
_ALLOWED_METHODS = "TEVION_CORS_ALLOWED_METHODS"
_ALLOWED_HEADERS = "TEVION_CORS_ALLOWED_HEADERS"

_LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]
_DEFAULT_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_DEFAULT_HEADERS = ["Authorization", "Content-Type"]


@dataclass(frozen=True)
class CorsSettings:
    environment: str
    allowed_origins: list[str]
    allowed_methods: list[str]
    allowed_headers: list[str]
    allow_credentials: bool = False


def _csv(value: str | None, default: list[str]) -> list[str]:
    if value is None:
        return default.copy()
    return [item.strip() for item in value.split(",") if item.strip()]


def get_cors_settings() -> CorsSettings:
    """Read the CORS policy from environment without exposing secret values."""
    environment = os.environ.get(_ENVIRONMENT, "local").strip().lower() or "local"
    configured_origins = os.environ.get(_ALLOWED_ORIGINS)
    if configured_origins is not None:
        allowed_origins = _csv(configured_origins, [])
    elif environment in {"local", "dev", "development"}:
        allowed_origins = _LOCAL_ORIGINS.copy()
    else:
        allowed_origins = []
        logger.warning(
            "%s is not configured for %s; browser cross-origin requests are disabled",
            _ALLOWED_ORIGINS,
            environment,
        )

    return CorsSettings(
        environment=environment,
        allowed_origins=allowed_origins,
        allowed_methods=_csv(os.environ.get(_ALLOWED_METHODS), _DEFAULT_METHODS),
        allowed_headers=_csv(os.environ.get(_ALLOWED_HEADERS), _DEFAULT_HEADERS),
    )


def configure_cors(app: FastAPI) -> CorsSettings:
    """Install the API CORS middleware and return the effective policy."""
    settings = get_cors_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
        allow_credentials=settings.allow_credentials,
    )
    return settings
