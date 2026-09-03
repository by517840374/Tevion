"""Bearer-token authentication boundary.

Tevion is a resource server: an external OAuth/OIDC provider owns login and
token issuance. This module extracts `Authorization: Bearer <token>`, verifies
the JWT (iss/aud/exp + signature), and maps the provider `sub` to the local
`users` table, creating the row on first sight (ADR-007).

Two verification modes, chosen by environment:
- dev:   TEVION_AUTH_DEV_SECRET set  -> HS256 self-signed tokens
- prod:  TEVION_OIDC_JWKS_URL set    -> RS256 via the provider JWKS

No secret is ever logged or committed.
"""

import os
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

AUTH_PROVIDER = "oidc"
DEFAULT_AUDIENCE = "tevion-api"

_ENV_ISSUER = "TEVION_OIDC_ISSUER"
_ENV_AUDIENCE = "TEVION_AUTH_AUDIENCE"
_ENV_JWKS_URL = "TEVION_OIDC_JWKS_URL"
_ENV_DEV_SECRET = "TEVION_AUTH_DEV_SECRET"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    audience: str
    jwks_url: str | None
    dev_secret: str | None


def get_auth_settings() -> AuthSettings:
    """Read settings on every call so tests can flip env vars without reload."""
    return AuthSettings(
        issuer=os.environ.get(_ENV_ISSUER, "tevion-local"),
        audience=os.environ.get(_ENV_AUDIENCE, DEFAULT_AUDIENCE),
        jwks_url=os.environ.get(_ENV_JWKS_URL) or None,
        dev_secret=os.environ.get(_ENV_DEV_SECRET) or None,
    )


def create_dev_token(subject: str, settings: AuthSettings | None = None) -> str:
    """Issue a short-lived HS256 token for local frontend development.

    Only available when a dev secret is configured; never enabled in
    JWKS/production mode.
    """
    import time

    settings = settings or get_auth_settings()
    if settings.jwks_url or not settings.dev_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dev token endpoint is disabled",
        )
    now = int(time.time())
    return jwt.encode(
        {
            "sub": subject,
            "iss": settings.issuer,
            "aud": settings.audience,
            "exp": now + 3600,
            "iat": now,
        },
        settings.dev_secret,
        algorithm="HS256",
    )


def decode_token(token: str, settings: AuthSettings | None = None) -> dict[str, Any]:
    settings = settings or get_auth_settings()
    if settings.jwks_url:
        key = jwt.PyJWKClient(settings.jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    if not settings.dev_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication is not configured",
        )
    return jwt.decode(
        token,
        settings.dev_secret,
        algorithms=["HS256"],
        audience=settings.audience,
        issuer=settings.issuer,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        claims = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(f"invalid token: {exc}") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized("token has no subject")

    user = db.scalar(
        select(User).where(
            User.auth_provider == AUTH_PROVIDER,
            User.provider_subject == subject,
        )
    )
    if user is None:
        email = claims.get("email")
        user = User(
            auth_provider=AUTH_PROVIDER,
            provider_subject=subject,
            email=email if isinstance(email, str) else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
