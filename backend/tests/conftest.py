import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
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
)

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# Smallest valid-looking payloads; the mock extractor never reads the bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 64


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TYPE IF EXISTS receipt_status"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    shutil.rmtree(_UPLOAD_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
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
