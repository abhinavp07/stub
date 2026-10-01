"""Fixed-window rate limiting backed by Postgres, so the limit holds across every API instance
without another service. One row per key, updated in place with a single upsert."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import case, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import RateLimit


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window: timedelta


LOGIN_PER_IP = Limit("login-ip", 20, timedelta(minutes=5))
LOGIN_PER_EMAIL = Limit("login-email", 10, timedelta(minutes=15))
SIGNUP_PER_IP = Limit("signup-ip", 10, timedelta(hours=1))
UPLOAD_PER_USER = Limit("upload-user", 120, timedelta(minutes=10))


class RateLimited(HTTPException):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's IP. X-Forwarded-For is only trusted for the configured number of proxy
    hops; otherwise anyone could pick their own rate-limit key."""
    if settings.trusted_proxy_hops > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [p for p in forwarded if p]
        if len(forwarded) >= settings.trusted_proxy_hops:
            return forwarded[-settings.trusted_proxy_hops]
    return request.client.host if request.client else "unknown"


async def hit(
    session: AsyncSession, limit: Limit, subject: str, now: datetime | None = None
) -> None:
    """Count one request against `limit` for `subject`; raise 429 when over. Commits."""
    now = now or datetime.now(UTC)
    seconds = int(limit.window.total_seconds())
    window_start = datetime.fromtimestamp(math.floor(now.timestamp() / seconds) * seconds, tz=UTC)
    key = f"{limit.name}:{subject}"
    stmt = insert(RateLimit).values(key=key, window_start=window_start, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[RateLimit.key],
        set_={
            "count": case(
                (RateLimit.window_start == stmt.excluded.window_start, RateLimit.count + 1),
                else_=1,
            ),
            "window_start": stmt.excluded.window_start,
        },
    ).returning(RateLimit.count)
    count = await session.scalar(stmt)
    await session.commit()
    if count is not None and count > limit.max_requests:
        retry = int((window_start + limit.window - now).total_seconds()) + 1
        raise RateLimited(max(retry, 1))


async def prune(session: AsyncSession, older_than: timedelta = timedelta(days=1)) -> int:
    """Delete stale counters; run periodically by the worker."""
    result = await session.execute(
        delete(RateLimit).where(RateLimit.window_start < func.now() - older_than)
    )
    await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined]


class RateLimiter:
    """Request-scoped helper: `await limiter.check(LIMIT, subject)`."""

    def __init__(self, session: AsyncSession, settings: Settings, request: Request) -> None:
        self.session = session
        self.settings = settings
        self.request = request

    @property
    def ip(self) -> str:
        return client_ip(self.request, self.settings)

    async def check(self, limit: Limit, subject: str) -> None:
        if self.settings.rate_limit_enabled:
            await hit(self.session, limit, subject)


def get_rate_limiter(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RateLimiter:
    return RateLimiter(session, settings, request)


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
