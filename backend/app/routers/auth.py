from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.auth import (
    CurrentUser,
    SessionDep,
    SettingsDep,
    clear_auth_cookie,
    create_access_token,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, UserOut
from app.services.defaults import seed_default_categories

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown, so login takes the same time either way.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> User:
    existing = await session.scalar(select(User.id).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or None,
    )
    session.add(user)
    await session.flush()
    seed_default_categories(session, user.id)
    await session.commit()
    set_auth_cookie(response, create_access_token(user.id, settings), settings)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> User:
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None:
        verify_password(_DUMMY_HASH, body.password)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    set_auth_cookie(response, create_access_token(user.id, settings), settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep) -> None:
    clear_auth_cookie(response, settings)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
