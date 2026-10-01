import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.services.parsing import (
    ParsedLineItem,
    ParsedReceipt,
    needs_review,
    parse_date,
    parse_expense,
    parse_money,
    parse_quantity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "textract"
THRESHOLD = 80.0
D = Decimal


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --- parse_money ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$1,234.50", D("1234.50")),
        ("1.234,50", D("1234.50")),
        ("1 234,50 €", D("1234.50")),
        ("12.00-", D("-12.00")),
        ("-$5.00", D("-5.00")),
        ("(3.00)", D("-3.00")),
        ("USD 7", D("7.00")),
        ("12,5", D("12.50")),
        (".99", D("0.99")),
        ("1,234", D("1234.00")),
        ("1.234.567", D("1234567.00")),
        ("1,234,567.89", D("1234567.89")),
        ("$ 4.99 T", D("4.99")),
        ("3.459", D("3.46")),  # a lone "." is always decimal (fuel prices)
        ("2.005", D("2.01")),
        ("1,234", D("1234.00")),  # a lone "," with 3 digits after is thousands
        ("3.456,7", D("3456.70")),
    ],
)
def test_parse_money(text: str, expected: Decimal) -> None:
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "$", "N/A", "--", "5-10", "abc", "1.2.3,4,5"])
def test_parse_money_returns_none_for_garbage(text: str | None) -> None:
    assert parse_money(text) is None


def test_parse_money_rounds_half_up_to_cents() -> None:
    assert parse_money("1.5") == D("1.50")


# --- parse_date -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-03-15", date(2024, 3, 15)),
        ("2024/01/07", date(2024, 1, 7)),
        ("03/15/2024", date(2024, 3, 15)),
        ("03/15/2024 14:32", date(2024, 3, 15)),
        ("3/5/24", date(2024, 3, 5)),
        ("15/03/2024", date(2024, 3, 15)),  # day > 12, so it must be day-first
        ("15.03.2024", date(2024, 3, 15)),
        ("15.03.24", date(2024, 3, 15)),
        ("Mar 2, 2024 7:41 PM", date(2024, 3, 2)),
        ("March 2 2024", date(2024, 3, 2)),
        ("Mar. 2, 2024", date(2024, 3, 2)),
        ("2 Mar 2024", date(2024, 3, 2)),
        ("02-Mar-2024".replace("-", " "), date(2024, 3, 2)),
        ("Date: 12/31/2023 Time: 23:59", date(2023, 12, 31)),
        ("20240315", date(2024, 3, 15)),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    "text", [None, "", "Thank you!", "13/13/2024", "99.99.9999", "Total 12.50", "01/01/1899"]
)
def test_parse_date_returns_none_for_garbage(text: str | None) -> None:
    assert parse_date(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2", D("2")), ("1.5 lb", D("1.5")), ("x3", D("3")), ("2,5 kg", D("2.5")), ("abc", None)],
)
def test_parse_quantity(text: str, expected: Decimal | None) -> None:
    assert parse_quantity(text) == expected


# --- parse_expense against fixtures ---------------------------------------------------------


def test_full_grocery_receipt() -> None:
    r = parse_expense(load("kroger_grocery"))
    assert r.merchant == "Kroger"
    assert r.purchase_date == date(2024, 3, 15)
    assert (r.subtotal, r.tax, r.tip, r.total) == (D("23.47"), D("1.64"), None, D("25.11"))
    # The duplicate, lower-confidence "BALANCE DUE" total is ignored.
    assert r.field_confidence["total"] == 99.5
    assert set(r.field_confidence) == {"merchant", "purchase_date", "subtotal", "tax", "total"}
    assert [li.description for li in r.line_items] == [
        "BANANAS",
        "KROGER 2% MILK GAL",
        "WHEAT BREAD",
        "CHICKEN BREAST",
        "LARGE EGGS 12CT",
    ]
    chicken = r.line_items[3]
    assert (chicken.quantity, chicken.unit_price, chicken.amount) == (D(2), D("6.00"), D("12.00"))
    assert not needs_review(r, THRESHOLD)


def test_fallback_types_tip_and_computed_line_amount() -> None:
    r = parse_expense(load("diner_tip_fallbacks"))
    assert r.merchant == "Joe's Diner"  # NAME used when VENDOR_NAME is missing
    assert r.total == D("54.08")  # AMOUNT_PAID used when TOTAL is missing
    assert r.tip == D("8.40")
    assert r.purchase_date == date(2024, 3, 2)
    iced_tea = r.line_items[2]
    assert iced_tea.amount == D("6.00")  # 2 x 3.00, no PRICE on the line
    assert not needs_review(r, THRESHOLD)


def test_missing_fields() -> None:
    r = parse_expense(load("missing_fields"))
    assert r.merchant == "Corner Store"
    assert r.purchase_date is None and r.total is None and r.subtotal is None
    assert r.line_items == []
    assert "total" not in r.field_confidence
    assert needs_review(r, THRESHOLD)


def test_european_money_and_date_formats() -> None:
    r = parse_expense(load("european_format"))
    assert r.merchant == "Café Müller GmbH"
    assert r.purchase_date == date(2024, 3, 15)
    assert (r.subtotal, r.tax, r.total) == (D("1234.50"), D("234.56"), D("1469.06"))
    assert r.line_items[0].amount == D("1234.50")
    assert not needs_review(r, THRESHOLD)


def test_refund_negative_amounts_and_low_confidence() -> None:
    r = parse_expense(load("low_confidence_refund"))
    assert r.merchant == "Best Buy"
    assert r.purchase_date == date(2024, 1, 7)
    assert r.total == D("-45.00")
    assert r.tax == D("-3.33")
    assert r.line_items[0].amount == D("-41.67")
    assert r.field_confidence["total"] == 61.2
    assert needs_review(r, THRESHOLD)
    assert not needs_review(r, 60.0)  # adds up, so only the confidence flagged it


def test_totals_that_dont_add_up_need_review() -> None:
    r = parse_expense(load("mismatch_totals"))
    assert r.total == D("15.00")
    assert sum(li.amount or 0 for li in r.line_items) + (r.tax or 0) == D("10.80")
    assert needs_review(r, THRESHOLD)


def test_empty_response() -> None:
    assert parse_expense(load("empty")) == ParsedReceipt()
    assert parse_expense({}) == ParsedReceipt()


def test_garbage_values_never_crash() -> None:
    r = parse_expense(load("garbage_values"))
    assert r.merchant is None
    assert r.purchase_date is None
    assert r.total is None and r.subtotal is None and r.tax is None
    assert r.line_items == []
    assert r.field_confidence == {}
    assert needs_review(r, THRESHOLD)


@pytest.mark.parametrize("name", [p.stem for p in FIXTURES.glob("*.json")])
def test_every_fixture_parses(name: str) -> None:
    parse_expense(load(name))


@pytest.mark.parametrize(
    "mock", [p.stem for p in (Path(__file__).parents[1] / "app/services/mock_responses").glob("*")]
)
def test_mock_responses_are_clean_receipts(mock: str) -> None:
    path = Path(__file__).parents[1] / "app/services/mock_responses" / f"{mock}.json"
    r = parse_expense(json.loads(path.read_text()))
    assert r.merchant and r.purchase_date and r.total and r.line_items
    assert not needs_review(r, THRESHOLD)


# --- needs_review rules ---------------------------------------------------------------------


def _ok(**overrides: Any) -> ParsedReceipt:
    base = ParsedReceipt(
        merchant="Shop",
        purchase_date=date(2024, 1, 1),
        tax=D("1.00"),
        total=D("11.00"),
        line_items=[ParsedLineItem("A", amount=D("4.00")), ParsedLineItem("B", amount=D("6.00"))],
        field_confidence={"merchant": 99, "purchase_date": 99, "total": 99},
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_needs_review_within_five_cents_is_fine() -> None:
    assert not needs_review(_ok(total=D("11.05")), THRESHOLD)
    assert needs_review(_ok(total=D("11.06")), THRESHOLD)


def test_needs_review_counts_tip() -> None:
    assert not needs_review(_ok(tip=D("2.00"), total=D("13.00")), THRESHOLD)


def test_needs_review_skips_sum_check_when_values_missing() -> None:
    assert not needs_review(_ok(tax=None, total=D("99.00")), THRESHOLD)
    items = [ParsedLineItem("A", amount=None), ParsedLineItem("B", amount=D("6.00"))]
    assert not needs_review(_ok(line_items=items, total=D("99.00")), THRESHOLD)
    assert not needs_review(_ok(line_items=[], total=D("99.00")), THRESHOLD)


def test_needs_review_low_confidence_key_field() -> None:
    conf = {"merchant": 99, "purchase_date": 79.9, "total": 99}
    assert needs_review(_ok(field_confidence=conf), THRESHOLD)
