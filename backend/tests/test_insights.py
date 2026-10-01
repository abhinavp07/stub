"""Insights, budgets and export against a small dataset whose totals were worked out by hand."""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Receipt, ReceiptStatus
from app.services.budgets import budget_status
from app.services.export import safe_text
from app.services.insights import Month
from tests.conftest import ClientFactory

D = Decimal


@dataclass
class Dataset:
    groceries: str
    dining: str
    transport: str


async def _user_id(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/auth/me")).json()["id"])


async def _cat(client: AsyncClient, name: str) -> str:
    return next(c["id"] for c in (await client.get("/api/categories")).json() if c["name"] == name)


async def _add(
    user_id: uuid.UUID,
    day: str | None,
    total: str | None,
    category: str | None = None,
    status: ReceiptStatus = ReceiptStatus.ready,
    **extra: object,
) -> None:
    async with SessionLocal() as s:
        s.add(
            Receipt(
                user_id=user_id,
                s3_key=f"users/{user_id}/receipts/{uuid.uuid4()}.jpg",
                original_filename="r.jpg",
                content_type="image/jpeg",
                status=status,
                purchase_date=date.fromisoformat(day) if day else None,
                total=D(total) if total is not None else None,
                category_id=uuid.UUID(category) if category else None,
                **extra,
            )
        )
        await s.commit()


@pytest.fixture
async def data(client: AsyncClient, make_client: ClientFactory) -> Dataset:
    """
    Month     | Groceries        | Dining                | Uncategorized | Month total
    2024-01   | 50.00            | 20.25                 |               |  70.25
    2024-02   |                  |                       |               |   0.00
    2024-03   | 100.10 + 0.90    | 12.34 (needs review)  | 33.33         | 146.67
    2024-04   |                  | -5.00 (refund)        |               |  -5.00
    All time  | 151.00           | 27.59                 | 33.33         | 211.92

    Plus rows that must never count: processing/failed receipts, a ready receipt with no
    total, one with no date, and another user's receipt.
    """
    uid = await _user_id(client)
    g, d, t = [await _cat(client, n) for n in ("Groceries", "Dining", "Transport")]
    await _add(uid, "2024-01-05", "50.00", g, merchant="Kroger", tags=["food", "weekly"])
    await _add(uid, "2024-01-31", "20.25", d, merchant="Joe's Diner", subtotal=D("18.00"),
               tax=D("1.25"), tip=D("1.00"), notes="lunch\nwith  Sam")  # fmt: skip
    await _add(uid, "2024-03-01", "100.10", g, merchant="Café Müller")
    await _add(uid, "2024-03-15", "0.90", g, merchant='=HYPERLINK("http://x")')
    await _add(uid, "2024-03-20", "12.34", d, merchant="Starbucks", needs_review=True)
    await _add(uid, "2024-03-31", "33.33", None, merchant="Corner Store")
    await _add(uid, "2024-04-02", "-5.00", d, merchant="Joe's Diner")
    # Never counted toward spending:
    await _add(uid, "2024-03-10", "999.00", g, status=ReceiptStatus.processing)
    await _add(uid, "2024-03-11", "999.00", g, status=ReceiptStatus.failed)
    await _add(uid, "2024-03-05", None, g, merchant="No total")
    await _add(uid, None, "500.00", g, merchant="No date")

    other = await make_client("other@example.com")
    await _add(await _user_id(other), "2024-03-02", "1000.00", await _cat(other, "Groceries"))
    return Dataset(g, d, t)


# --- Summary --------------------------------------------------------------------------------


async def test_summary_matches_hand_totals(client: AsyncClient, data: Dataset) -> None:
    body = (await client.get("/api/insights/summary", params={"month": "2024-03"})).json()
    assert body == {
        "month": "2024-03",
        "currency": "USD",
        "total": "146.67",
        "receipt_count": 4,
        "previous_month": "2024-02",
        "previous_total": "0.00",
        "previous_receipt_count": 0,
        "change_pct": None,  # nothing to compare against
        "needs_review_count": 1,
    }


@pytest.mark.parametrize(
    ("month", "total", "previous", "change"),
    [
        ("2024-01", "70.25", "0.00", None),
        ("2024-02", "0.00", "70.25", "-100.0"),
        ("2024-04", "-5.00", "146.67", "-103.4"),  # (-5 - 146.67) / 146.67
        ("2024-05", "0.00", "-5.00", "100.0"),
    ],
)
async def test_summary_month_over_month(
    client: AsyncClient, data: Dataset, month: str, total: str, previous: str, change: str | None
) -> None:
    body = (await client.get("/api/insights/summary", params={"month": month})).json()
    assert (body["total"], body["previous_total"], body["change_pct"]) == (total, previous, change)


async def test_summary_month_validation(client: AsyncClient) -> None:
    for bad in ("2024-13", "2024-3", "march"):
        resp = await client.get("/api/insights/summary", params={"month": bad})
        assert resp.status_code == 422


# --- By category ----------------------------------------------------------------------------


async def test_by_category_for_a_month(client: AsyncClient, data: Dataset) -> None:
    body = (
        await client.get(
            "/api/insights/by-category", params={"from": "2024-03-01", "to": "2024-03-31"}
        )
    ).json()
    assert body["total"] == "146.67"
    assert [(i["name"], i["total"], i["receipt_count"]) for i in body["items"]] == [
        ("Groceries", "101.00", 2),
        ("Uncategorized", "33.33", 1),
        ("Dining", "12.34", 1),
    ]
    assert body["items"][1]["category_id"] is None
    assert body["items"][0]["category_id"] == data.groceries


async def test_by_category_all_time_and_inclusive_bounds(
    client: AsyncClient, data: Dataset
) -> None:
    body = (await client.get("/api/insights/by-category")).json()
    assert body["total"] == "211.92"
    assert {i["name"]: i["total"] for i in body["items"]} == {
        "Groceries": "151.00",
        "Uncategorized": "33.33",
        "Dining": "27.59",
    }
    # Both ends inclusive: Jan 31 and Mar 1 are in.
    body = (
        await client.get(
            "/api/insights/by-category", params={"from": "2024-01-31", "to": "2024-03-01"}
        )
    ).json()
    assert body["total"] == "120.35"  # 20.25 + 100.10


async def test_by_category_empty_and_invalid_range(client: AsyncClient, data: Dataset) -> None:
    body = (await client.get("/api/insights/by-category", params={"from": "2030-01-01"})).json()
    assert body == {"currency": "USD", "total": "0.00", "items": []}
    resp = await client.get(
        "/api/insights/by-category", params={"from": "2024-02-01", "to": "2024-01-01"}
    )
    assert resp.status_code == 422


# --- Trend ----------------------------------------------------------------------------------


async def test_trend_fills_empty_months(client: AsyncClient, data: Dataset) -> None:
    body = (await client.get("/api/insights/trend", params={"months": 6, "end": "2024-04"})).json()
    assert [(m["month"], m["total"], m["receipt_count"]) for m in body["months"]] == [
        ("2023-11", "0.00", 0),
        ("2023-12", "0.00", 0),
        ("2024-01", "70.25", 2),
        ("2024-02", "0.00", 0),
        ("2024-03", "146.67", 4),
        ("2024-04", "-5.00", 1),
    ]
    assert all(m["by_category"] is None for m in body["months"])


async def test_trend_by_category(client: AsyncClient, data: Dataset) -> None:
    body = (
        await client.get(
            "/api/insights/trend", params={"months": 1, "end": "2024-03", "by_category": True}
        )
    ).json()
    [march] = body["months"]
    assert {c["category_id"]: c["total"] for c in march["by_category"]} == {
        data.groceries: "101.00",
        None: "33.33",
        data.dining: "12.34",
    }


async def test_trend_with_no_data_and_bounds(client: AsyncClient) -> None:
    body = (await client.get("/api/insights/trend", params={"months": 12})).json()
    assert len(body["months"]) == 12
    assert body["months"][-1]["month"] == str(Month.current())
    assert all(m["total"] == "0.00" for m in body["months"])
    assert (await client.get("/api/insights/trend", params={"months": 0})).status_code == 422
    assert (await client.get("/api/insights/trend", params={"months": 37})).status_code == 422


def test_month_arithmetic() -> None:
    assert Month(2024, 1).shift(-1) == Month(2023, 12)
    assert Month(2024, 12).shift(1) == Month(2025, 1)
    assert Month(2024, 3).shift(-14) == Month(2023, 1)
    assert Month(2024, 2).next_first_day == date(2024, 3, 1)
    assert str(Month.parse("2024-07")) == "2024-07"


# --- Budgets --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spent", "limit", "threshold", "expected"),
    [
        ("0", "100", 80, "ok"),
        ("79.99", "100", 80, "ok"),
        ("80.00", "100", 80, "warning"),  # amber exactly at the threshold
        ("100.00", "100", 80, "warning"),  # 100% is still amber
        ("100.01", "100", 80, "over"),  # red only above 100%
        ("100.00", "100", 100, "warning"),
        ("-5", "100", 80, "ok"),
    ],
)
def test_budget_status(spent: str, limit: str, threshold: int, expected: str) -> None:
    assert budget_status(D(spent), D(limit), threshold) == expected


async def test_budgets_report_spent_for_the_month(client: AsyncClient, data: Dataset) -> None:
    put = await client.put(f"/api/budgets/{data.groceries}", json={"monthly_limit": "120"})
    assert put.status_code == 200
    assert put.json()["alert_threshold_pct"] == 80
    await client.put(
        f"/api/budgets/{data.dining}", json={"monthly_limit": "10.00", "alert_threshold_pct": 50}
    )
    await client.put(f"/api/budgets/{data.transport}", json={"monthly_limit": "50"})

    body = (await client.get("/api/budgets", params={"month": "2024-03"})).json()
    got = {
        b["category_name"]: (b["spent"], b["remaining"], b["percent_used"], b["status"])
        for b in body
    }
    assert got == {
        "Dining": ("12.34", "-2.34", "123.4", "over"),
        "Groceries": ("101.00", "19.00", "84.2", "warning"),
        "Transport": ("0.00", "50.00", "0.0", "ok"),
    }
    assert [b["category_name"] for b in body] == ["Dining", "Groceries", "Transport"]


async def test_budget_update_and_delete(client: AsyncClient, data: Dataset) -> None:
    url = f"/api/budgets/{data.groceries}"
    await client.put(url, json={"monthly_limit": "100"})
    resp = await client.put(url, json={"monthly_limit": "250.50", "alert_threshold_pct": 90})
    assert (resp.json()["monthly_limit"], resp.json()["alert_threshold_pct"]) == ("250.50", 90)
    assert len((await client.get("/api/budgets")).json()) == 1

    assert (await client.delete(url)).status_code == 204
    assert (await client.get("/api/budgets")).json() == []
    assert (await client.delete(url)).status_code == 404


async def test_budget_validation(client: AsyncClient, data: Dataset) -> None:
    url = f"/api/budgets/{data.groceries}"
    for body in (
        {"monthly_limit": "0"},
        {"monthly_limit": "-1"},
        {"monthly_limit": "1.234"},
        {"monthly_limit": "10", "alert_threshold_pct": 0},
        {"monthly_limit": "10", "alert_threshold_pct": 101},
    ):
        assert (await client.put(url, json=body)).status_code == 422, body


async def test_deleting_category_removes_its_budget(client: AsyncClient, data: Dataset) -> None:
    await client.put(f"/api/budgets/{data.groceries}", json={"monthly_limit": "100"})
    await client.delete(f"/api/categories/{data.groceries}")
    assert (await client.get("/api/budgets")).json() == []


async def test_budgets_are_private(make_client: ClientFactory) -> None:
    owner = await make_client("owner@example.com")
    intruder = await make_client("intruder@example.com")
    cat = await _cat(owner, "Groceries")
    await owner.put(f"/api/budgets/{cat}", json={"monthly_limit": "100"})

    assert (
        await intruder.put(f"/api/budgets/{cat}", json={"monthly_limit": "1"})
    ).status_code == 404
    assert (await intruder.delete(f"/api/budgets/{cat}")).status_code == 404
    assert (await intruder.get("/api/budgets")).json() == []
    assert (await owner.get("/api/budgets")).json()[0]["monthly_limit"] == "100.00"


# --- Export ---------------------------------------------------------------------------------


def _parse(resp_text: str) -> list[list[str]]:
    assert resp_text.startswith("﻿")
    return list(csv.reader(io.StringIO(resp_text.removeprefix("﻿"))))


async def test_export_csv(client: AsyncClient, data: Dataset) -> None:
    resp = await client.get("/api/export/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert resp.headers["content-disposition"].startswith('attachment; filename="receipts-')
    assert "\r\n" in resp.text

    rows = _parse(resp.text)
    assert rows[0] == [
        "date", "merchant", "category", "subtotal", "tax", "tip", "total", "tags", "notes",
    ]  # fmt: skip
    body = rows[1:]
    # One row per ready receipt (9 ready for this user), oldest first, undated last.
    assert len(body) == 9
    assert body[0] == [
        "2024-01-05", "Kroger", "Groceries", "", "", "", "50.00", "food; weekly", "",
    ]  # fmt: skip
    assert body[1] == [
        "2024-01-31", "Joe's Diner", "Dining", "18.00", "1.25", "1.00", "20.25", "",
        "lunch with Sam",
    ]  # fmt: skip
    by_merchant = {r[1]: r for r in body}
    assert by_merchant["Café Müller"][6] == "100.10"
    assert '\'=HYPERLINK("http://x")' in by_merchant  # formula neutralized
    assert by_merchant["Corner Store"][2] == ""  # uncategorized
    assert by_merchant["No total"][6] == ""
    assert body[-1][1] == "No date" and body[-1][0] == ""
    refund = next(r for r in body if r[0] == "2024-04-02")
    assert refund[6] == "-5.00"  # numbers are never prefixed
    assert "1000.00" not in resp.text  # other user's data


async def test_export_filters(client: AsyncClient, data: Dataset) -> None:
    resp = await client.get(
        "/api/export/csv",
        params={"from": "2024-03-01", "to": "2024-03-31", "category_id": data.groceries},
    )
    body = _parse(resp.text)[1:]
    assert [(r[0], r[6]) for r in body] == [
        ("2024-03-01", "100.10"),
        ("2024-03-05", ""),
        ("2024-03-15", "0.90"),
    ]
    none = _parse((await client.get("/api/export/csv", params={"category_id": "none"})).text)
    assert [r[1] for r in none[1:]] == ["Corner Store"]
    bad = await client.get("/api/export/csv", params={"category_id": "groceries"})
    assert bad.status_code == 422


async def test_export_with_no_receipts_is_just_a_header(client: AsyncClient) -> None:
    rows = _parse((await client.get("/api/export/csv")).text)
    assert len(rows) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [("=1+1", "'=1+1"), ("+cmd", "'+cmd"), ("-x", "'-x"), ("@SUM", "'@SUM"), ("Shell", "Shell"),
     ("", ""), (None, "")],
)  # fmt: skip
def test_safe_text(value: str | None, expected: str) -> None:
    assert safe_text(value) == expected


async def test_insights_require_auth(make_client: ClientFactory) -> None:
    anon = await make_client()
    for path in (
        "/api/insights/summary",
        "/api/insights/by-category",
        "/api/insights/trend",
        "/api/budgets",
        "/api/export/csv",
    ):
        assert (await anon.get(path)).status_code == 401, path
