from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from starlette.requests import Request

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.services.ratelimit import Limit, RateLimited, client_ip, hit
from tests.conftest import ClientFactory


@pytest.fixture
def limits_on() -> None:
    settings = get_settings().model_copy(update={"rate_limit_enabled": True})
    app.dependency_overrides[get_settings] = lambda: settings


async def test_login_is_limited_per_email(make_client: ClientFactory, limits_on: None) -> None:
    await make_client("victim@example.com")
    attacker = await make_client()
    creds = {"email": "victim@example.com", "password": "wrong-password"}
    for _ in range(10):
        assert (await attacker.post("/api/auth/login", json=creds)).status_code == 401
    blocked = await attacker.post("/api/auth/login", json=creds)
    assert blocked.status_code == 429
    assert blocked.json()["detail"].startswith("Too many attempts. Try again in ")
    assert int(blocked.headers["retry-after"]) > 0
    # Even the right password is refused until the window passes.
    ok = {"email": "victim@example.com", "password": "correct-horse"}
    assert (await attacker.post("/api/auth/login", json=ok)).status_code == 429


async def test_signup_is_limited_per_ip(make_client: ClientFactory, limits_on: None) -> None:
    client = await make_client()
    for i in range(10):
        r = await client.post(
            "/api/auth/signup", json={"email": f"u{i}@x.co", "password": "longenough"}
        )
        assert r.status_code == 201
        client.cookies.clear()
    r = await client.post("/api/auth/signup", json={"email": "u99@x.co", "password": "longenough"})
    assert r.status_code == 429


async def test_upload_urls_are_limited_per_user(client: AsyncClient, limits_on: None) -> None:
    body = {"filename": "r.jpg", "content_type": "image/jpeg", "size_bytes": 10}
    for _ in range(120):
        assert (await client.post("/api/receipts/upload-url", json=body)).status_code == 201
    assert (await client.post("/api/receipts/upload-url", json=body)).status_code == 429


async def test_fixed_window_resets() -> None:
    limit = Limit("test", 2, timedelta(minutes=1))
    t0 = datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC)
    async with SessionLocal() as s:
        await hit(s, limit, "k", now=t0)
        await hit(s, limit, "k", now=t0 + timedelta(seconds=10))
        with pytest.raises(RateLimited) as exc:
            await hit(s, limit, "k", now=t0 + timedelta(seconds=20))
        assert exc.value.headers == {"Retry-After": "36"}
        # A new window starts fresh.
        await hit(s, limit, "k", now=t0 + timedelta(minutes=1))
        # Other subjects have their own counters.
        await hit(s, limit, "other", now=t0 + timedelta(seconds=20))


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("hops", "xff", "expected"),
    [
        (0, "1.1.1.1", "10.0.0.1"),  # untrusted header ignored
        (1, "1.1.1.1", "1.1.1.1"),
        (1, "6.6.6.6, 1.1.1.1", "1.1.1.1"),  # client-supplied prefix can't spoof
        (2, "6.6.6.6, 1.1.1.1, 2.2.2.2", "1.1.1.1"),
        (2, "1.1.1.1", "10.0.0.1"),  # fewer hops than expected: fall back to peer
    ],
)
def test_client_ip(hops: int, xff: str, expected: str) -> None:
    settings = get_settings().model_copy(update={"trusted_proxy_hops": hops})
    assert client_ip(_request("10.0.0.1", xff), settings) == expected
