import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path

import pytest

# Configure before the app is imported: settings and the engine are created at import time.
_UPLOAD_DIR = tempfile.mkdtemp(prefix="receipt-tests-")
os.environ.update(
    DATABASE_URL=os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://receipts:receipts@localhost:5432/receipts_test",
    ),
    TEXTRACT_MODE="mock",  # never call real Textract in tests
    STORAGE_MODE="local",
    LOCAL_UPLOAD_DIR=_UPLOAD_DIR,
    MOCK_TEXTRACT_DELAY_SECONDS="0",
    JWT_SECRET="test-secret-that-is-long-enough-for-hs256",
    RATE_LIMIT_ENABLED="false",  # rate-limit tests turn it back on explicitly
    EMAIL_MODE="log",
    SQS_QUEUE_URL="",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

# Smallest valid-looking payloads; the mock extractor never reads the bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 64


def _reset_and_migrate() -> None:
    """Build the test schema with the real migrations (which also seed global merchant rules)."""

    async def reset() -> None:
        eng = create_async_engine(os.environ["DATABASE_URL"])
        async with eng.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await eng.dispose()

    asyncio.run(reset())
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    # Sync on purpose: alembic's env.py runs its own event loop.
    _reset_and_migrate()
    yield
    shutil.rmtree(_UPLOAD_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    # Deleting users cascades to all user data and leaves the seeded global rules in place.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM users"))
        await conn.execute(text("DELETE FROM rate_limits"))
    app.dependency_overrides.clear()


ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def make_client() -> AsyncIterator[ClientFactory]:
    """Returns a factory for clients; pass an email to get one that's signed up and logged in."""
    clients: list[AsyncClient] = []

    async def factory(email: str | None = None, password: str = "correct-horse") -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        if email:
            resp = await client.post(
                "/api/auth/signup", json={"email": email, "password": password}
            )
            assert resp.status_code == 201, resp.text
        return client

    yield factory
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncClient:
    """A logged-in user."""
    return await make_client("alice@example.com")


async def upload_receipt(
    client: AsyncClient,
    data: bytes = JPEG_BYTES,
    content_type: str = "image/jpeg",
    filename: str = "receipt.jpg",
) -> dict:
    """Run the full upload flow (upload-url -> direct upload -> complete) and return the
    receipt after background processing has finished."""
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": filename, "content_type": content_type, "size_bytes": len(data)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    up = await client.post(
        body["upload_url"], data=body["fields"], files={"file": (filename, data, content_type)}
    )
    assert up.status_code == 204, up.text
    done = await client.post(f"/api/receipts/{body['receipt_id']}/complete")
    assert done.status_code == 200, done.text
    # ASGITransport runs background tasks before returning, so processing is finished.
    detail = await client.get(f"/api/receipts/{body['receipt_id']}")
    assert detail.status_code == 200
    return detail.json()


class SampleExtractor:
    """Always returns one named mock response, so tests can choose the merchant."""

    def __init__(self, sample: str) -> None:
        self.sample = sample

    async def analyze(self, doc: object, key: str) -> dict:
        from app.services.textract import MOCK_RESPONSES_DIR

        return json.loads((MOCK_RESPONSES_DIR / f"{self.sample}.json").read_text())


def use_sample(sample: str) -> None:
    """Make every upload extract as the given mock response: grocery (Kroger), restaurant
    (Joe's Diner) or gas_station (Shell)."""
    from app.services.textract import get_extractor

    app.dependency_overrides[get_extractor] = lambda: SampleExtractor(sample)
