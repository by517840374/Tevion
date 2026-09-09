"""Password and bearer-token authentication boundary."""

import os
from dataclasses import dataclass
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

AUTH_PROVIDER = "oidc"
LOCAL_AUTH_PROVIDER = "local"
DEFAULT_AUDIENCE = "tevion-api"

_ENV_ISSUER = "TEVION_OIDC_ISSUER"
_ENV_AUDIENCE = "TEVION_AUTH_AUDIENCE"
_ENV_JWKS_URL = "TEVION_OIDC_JWKS_URL"
_ENV_DEV_SECRET = "TEVION_AUTH_DEV_SECRET"

_bearer = HTTPBearer(auto_error=False)
_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    audience: str
    jwks_url: str | None
    dev_secret: str | None


def get_auth_settings() -> AuthSettings:
    return AuthSettings(
        issuer=os.environ.get(_ENV_ISSUER, "tevion-local"),
        audience=os.environ.get(_ENV_AUDIENCE, DEFAULT_AUDIENCE),
        jwks_url=os.environ.get(_ENV_JWKS_URL) or None,
        dev_secret=os.environ.get(_ENV_DEV_SECRET) or None,
    )


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def create_access_token(
    subject: str,
    *,
    auth_provider: str = AUTH_PROVIDER,
    settings: AuthSettings | None = None,
) -> str:
    import time

    settings = settings or get_auth_settings()
    if settings.jwks_url or not settings.dev_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication is not configured")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": subject,
            "auth_provider": auth_provider,
            "iss": settings.issuer,
            "aud": settings.audience,
            "exp": now + 3600,
            "iat": now,
        },
        settings.dev_secret,
        algorithm="HS256",
    )


def create_dev_token(subject: str, settings: AuthSettings | None = None) -> str:
    return create_access_token(subject, settings=settings)


def create_local_token(email: str, settings: AuthSettings | None = None) -> str:
    return create_access_token(normalize_email(email), auth_provider=LOCAL_AUTH_PROVIDER, settings=settings)


def decode_token(token: str, settings: AuthSettings | None = None) -> dict[str, Any]:
    settings = settings or get_auth_settings()
    if settings.jwks_url:
        key = jwt.PyJWKClient(settings.jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["RS256"], audience=settings.audience, issuer=settings.issuer)
    if not settings.dev_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication is not configured")
    return jwt.decode(
        token,
        settings.dev_secret,
        algorithms=["HS256"],
        audience=settings.audience,
        issuer=settings.issuer,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication failed")


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
    auth_provider = claims.get("auth_provider", AUTH_PROVIDER)
    if not isinstance(subject, str) or not subject or not isinstance(auth_provider, str) or not auth_provider:
        raise _unauthorized("invalid identity")

    user = db.scalar(select(User).where(User.auth_provider == auth_provider, User.provider_subject == subject))
    if user is None:
        email = claims.get("email")
        user = User(
            auth_provider=auth_provider,
            provider_subject=subject,
            email=email if isinstance(email, str) else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
