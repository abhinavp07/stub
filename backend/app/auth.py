import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User

COOKIE_NAME = "access_token"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.jwt_expires_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_auth_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/"
    )


_unauthenticated = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    if not access_token:
        raise _unauthenticated
    try:
        payload = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("typ") != "access":
            raise _unauthenticated
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthenticated from None
    user = await session.get(User, user_id)
    if user is None:
        raise _unauthenticated
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
