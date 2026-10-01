from httpx import AsyncClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Category
from tests.conftest import ClientFactory


async def test_signup_sets_cookie_and_seeds_categories(make_client: ClientFactory) -> None:
    client = await make_client()
    resp = await client.post(
        "/api/auth/signup",
        json={"email": "  New.User@Example.COM ", "password": "longenough", "display_name": "N"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new.user@example.com"
    cookie = resp.headers["set-cookie"].lower()
    assert "access_token=" in cookie and "httponly" in cookie and "samesite=lax" in cookie

    async with SessionLocal() as s:
        count = await s.scalar(select(func.count()).select_from(Category))
    assert count == 10


async def test_signup_duplicate_email_conflicts(make_client: ClientFactory) -> None:
    await make_client("dup@example.com")
    other = await make_client()
    resp = await other.post(
        "/api/auth/signup", json={"email": "DUP@example.com", "password": "longenough"}
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "An account with this email already exists"}


async def test_signup_validation_errors_use_detail_string(make_client: ClientFactory) -> None:
    client = await make_client()
    resp = await client.post("/api/auth/signup", json={"email": "nope", "password": "short"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert "email" in detail and "password" in detail


async def test_login_logout_me(make_client: ClientFactory) -> None:
    await make_client("bob@example.com", password="bobs-password")
    client = await make_client()

    assert (await client.get("/api/auth/me")).status_code == 401

    bad = await client.post(
        "/api/auth/login", json={"email": "bob@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    assert bad.json() == {"detail": "Invalid email or password"}
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert unknown.status_code == 401

    ok = await client.post(
        "/api/auth/login", json={"email": "BOB@example.com", "password": "bobs-password"}
    )
    assert ok.status_code == 200
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.com"

    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_tampered_token_is_rejected(client: AsyncClient) -> None:
    client.cookies.set("access_token", "not.a.jwt")
    assert (await client.get("/api/auth/me")).status_code == 401
