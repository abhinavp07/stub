import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import BudgetAlert, Receipt, ReceiptStatus
from app.services.alerts import Email, LogMailer, SesMailer, check_budget_alerts, get_mailer
from app.services.insights import Month
from tests.conftest import upload_receipt, use_sample


async def _setup(client: AsyncClient, limit: str, threshold: int = 80) -> tuple[uuid.UUID, str]:
    me = (await client.get("/api/auth/me")).json()
    cat = next(c for c in (await client.get("/api/categories")).json() if c["name"] == "Dining")
    resp = await client.put(
        f"/api/budgets/{cat['id']}",
        json={"monthly_limit": limit, "alert_threshold_pct": threshold},
    )
    assert resp.status_code == 200
    return uuid.UUID(me["id"]), cat["id"]


async def _spend(user_id: uuid.UUID, category_id: str, total: str, day: date | None = None) -> None:
    async with SessionLocal() as s:
        s.add(
            Receipt(
                user_id=user_id,
                s3_key=f"users/{user_id}/receipts/{uuid.uuid4()}.jpg",
                original_filename="r.jpg",
                content_type="image/jpeg",
                status=ReceiptStatus.ready,
                purchase_date=day or Month.current().first_day,
                total=Decimal(total),
                category_id=uuid.UUID(category_id),
            )
        )
        await s.commit()


async def _check(user_id: uuid.UUID, mailer: LogMailer, month: Month | None = None) -> list[Email]:
    async with SessionLocal() as s:
        return await check_budget_alerts(
            s, user_id, month or Month.current(), mailer, "https://app.example"
        )


async def test_alert_sent_once_per_category_per_month(client: AsyncClient) -> None:
    user_id, cat = await _setup(client, "100")
    mailer = LogMailer()
    await _spend(user_id, cat, "79.99")
    assert await _check(user_id, mailer) == []

    await _spend(user_id, cat, "0.01")  # exactly 80%
    [email] = await _check(user_id, mailer)
    assert email.to == "alice@example.com"
    assert email.subject == "You've used 80.0% of your Dining budget"
    assert "80.00 USD of your 100.00 USD Dining budget" in email.text
    assert "https://app.example/budgets" in email.text

    # Going over later in the month doesn't send a second email.
    await _spend(user_id, cat, "50.00")
    assert await _check(user_id, mailer) == []
    assert len(mailer.sent) == 1


async def test_jumping_straight_over_says_over(client: AsyncClient) -> None:
    user_id, cat = await _setup(client, "40")
    await _spend(user_id, cat, "55.50")
    [email] = await _check(user_id, LogMailer())
    assert email.subject.startswith("You're over your Dining budget")
    assert "15.50 USD over" in email.text


async def test_no_alerts_for_past_months(client: AsyncClient) -> None:
    user_id, cat = await _setup(client, "10")
    last_month = Month.current().shift(-1)
    await _spend(user_id, cat, "500", day=last_month.first_day)
    assert await _check(user_id, LogMailer(), last_month) == []


async def test_concurrent_checks_send_one_email(client: AsyncClient) -> None:
    user_id, cat = await _setup(client, "10")
    await _spend(user_id, cat, "20")
    mailer = LogMailer()
    await asyncio.gather(*(_check(user_id, mailer) for _ in range(5)))
    assert len(mailer.sent) == 1
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(BudgetAlert)))
    assert [(r.month, r.status) for r in rows] == [(str(Month.current()), "over")]


async def test_failed_send_is_not_retried(client: AsyncClient) -> None:
    user_id, cat = await _setup(client, "10")
    await _spend(user_id, cat, "20")

    class Broken(LogMailer):
        async def send(self, email: Email) -> None:
            raise RuntimeError("SES down")

    assert await _check(user_id, Broken()) == []  # logged, not raised
    later = LogMailer()
    assert await _check(user_id, later) == []  # at most once
    assert later.sent == []


async def test_editing_a_receipt_triggers_the_alert(client: AsyncClient) -> None:
    mailer = LogMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    _, cat = await _setup(client, "20")
    use_sample("restaurant")
    receipt = await upload_receipt(client)  # dated 2024: no alert for an old month
    assert mailer.sent == []

    await client.patch(
        f"/api/receipts/{receipt['id']}",
        json={"purchase_date": str(Month.current().first_day), "category_id": cat},
    )
    assert [e.subject for e in mailer.sent] == [
        "You're over your Dining budget for " + (f"{Month.current().first_day:%B %Y}")
    ]


async def test_processing_triggers_the_alert(client: AsyncClient) -> None:
    """A receipt extracted with a date in the current month is checked after processing."""
    mailer = LogMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    user_id, cat = await _setup(client, "5")

    from app.services.textract import get_extractor
    from tests.conftest import SampleExtractor

    class ThisMonth(SampleExtractor):
        async def analyze(self, doc: object, key: str) -> dict:
            data = await super().analyze(doc, key)
            for f in data["ExpenseDocuments"][0]["SummaryFields"]:
                if f["Type"]["Text"] == "INVOICE_RECEIPT_DATE":
                    f["ValueDetection"]["Text"] = str(Month.current().first_day)
                    f["ValueDetection"].pop("NormalizedValue", None)
            return data

    app.dependency_overrides[get_extractor] = lambda: ThisMonth("restaurant")
    # Joe's Diner has no rule; teach one so it lands in Dining.
    first = await upload_receipt(client)
    await client.patch(f"/api/receipts/{first['id']}", json={"category_id": cat})
    mailer.sent.clear()
    async with SessionLocal() as s:
        await s.execute(BudgetAlert.__table__.delete())
        await s.commit()

    second = await upload_receipt(client)
    assert second["category_id"] == cat
    assert len(mailer.sent) == 1


async def test_ses_mailer_sends_plain_text() -> None:
    calls: list[dict] = []

    class FakeSes:
        def send_email(self, **kwargs: object) -> None:
            calls.append(kwargs)

    mailer = SesMailer("Receipts <alerts@example.com>", "us-east-1", client=FakeSes())
    await mailer.send(Email(to="a@b.co", subject="Hi", text="Body"))
    assert calls == [
        {
            "FromEmailAddress": "Receipts <alerts@example.com>",
            "Destination": {"ToAddresses": ["a@b.co"]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": "Hi", "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": "Body", "Charset": "UTF-8"}},
                }
            },
        }
    ]


@pytest.fixture(autouse=True)
def _no_real_ses() -> None:
    """Budget PUTs schedule alert checks; keep them on the log mailer."""
    app.dependency_overrides.setdefault(get_mailer, lambda: LogMailer())
