"""Normalize an Amazon Textract AnalyzeExpense response into a receipt.

Everything here is pure: no I/O, no database, no settings. Every parser returns None rather
than raising when the input is unusable, because OCR output is messy and a half-filled receipt
the user can correct beats a failed one.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
TOTALS_TOLERANCE = Decimal("0.05")

# Summary field types, in order of preference.
MERCHANT_TYPES = ("VENDOR_NAME", "NAME")
DATE_TYPES = ("INVOICE_RECEIPT_DATE",)
SUBTOTAL_TYPES = ("SUBTOTAL",)
TAX_TYPES = ("TAX",)
TIP_TYPES = ("GRATUITY",)
TOTAL_TYPES = ("TOTAL", "AMOUNT_PAID")

# Fields that must be present and confident, or the receipt needs review.
KEY_FIELDS = ("merchant", "purchase_date", "total")


@dataclass
class ParsedLineItem:
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass
class ParsedReceipt:
    merchant: str | None = None
    purchase_date: date | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    total: Decimal | None = None
    line_items: list[ParsedLineItem] = field(default_factory=list)
    # Textract confidence (0-100) for each scalar field that was found.
    field_confidence: dict[str, float] = field(default_factory=dict)


# --- Money ----------------------------------------------------------------------------------

_MONEY_CHARS = re.compile(r"[^0-9.,\-()]")


def parse_money(text: str | None) -> Decimal | None:
    """Parse OCR'd money like "$1,234.50", "1.234,50", "12.00-", "(3.00)", "USD 7".

    The decimal separator is inferred: with both "," and "." the last one wins. A lone "." is
    always decimal (fuel prices like "3.459" are common); a lone "," is decimal only when 1-2
    digits follow it ("12,50"), otherwise thousands ("1,234"). A separator that repeats is
    thousands. Returns None when no number can be read.
    """
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None

    negative = False
    if s.endswith("-") or (s.startswith("(") and s.endswith(")")):
        negative = True
    s = _MONEY_CHARS.sub("", s).strip("()")
    if s.startswith("-"):
        negative = True
    s = s.strip("-")
    if not s or "-" in s or "(" in s or ")" in s:
        return None

    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        tail = s.rpartition(sep)[2]
        if s.count(sep) > 1:
            decimal_sep = None  # "1,234,567" / "1.234.567"
        elif sep == ".":
            decimal_sep = "."
        else:
            decimal_sep = "," if 1 <= len(tail) <= 2 else None
    else:
        decimal_sep = None

    thousands_sep = {",": ".", ".": ","}.get(decimal_sep or "")
    if decimal_sep is None:
        s = s.replace(",", "").replace(".", "")
    else:
        if thousands_sep:
            s = s.replace(thousands_sep, "")
        s = s.replace(decimal_sep, ".")
    if s.count(".") > 1 or not re.fullmatch(r"\d*\.?\d*", s) or not any(c.isdigit() for c in s):
        return None

    try:
        value = Decimal(s).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return -value if negative else value


_QTY_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_quantity(text: str | None) -> Decimal | None:
    """First number in the text: "2", "1.5 lb", "x3", "2,5 kg"."""
    if not text:
        return None
    m = _QTY_RE.search(text)
    if not m:
        return None
    try:
        q = Decimal(m.group().replace(",", "."))
    except InvalidOperation:
        return None
    return q if q > 0 else None


# --- Dates ----------------------------------------------------------------------------------

# Tried in order. US month-first comes before day-first; day-first catches days > 12.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%b %d %Y",
    "%B %d %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %y",
    "%d %b %y",
    "%Y%m%d",
)
_DATE_TOKEN = re.compile(
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"  # 2024-03-15
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"  # 03/15/2024, 15.03.24
    r"|[A-Za-z]{3,9}\.? \d{1,2},? \d{2,4}"  # Mar 15, 2024
    r"|\d{1,2} [A-Za-z]{3,9}\.?,? \d{2,4}"  # 15 Mar 2024
    r"|\d{8}"  # 20240315
)
MIN_YEAR = 2000


def parse_date(text: str | None) -> date | None:
    """Parse a receipt date from text that may also contain a time or other noise."""
    if not text:
        return None
    m = _DATE_TOKEN.search(text.strip())
    if not m:
        return None
    token = re.sub(r"[.,]?\s+", " ", m.group()).replace(",", "")
    token = re.sub(r"^([A-Za-z]{3,9})\.", r"\1", token)
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(token, fmt).date()
        except ValueError:
            continue
        if d.year >= MIN_YEAR:
            return d
    return None


# --- Textract structure ---------------------------------------------------------------------


@dataclass
class _Field:
    type: str
    text: str | None
    confidence: float
    normalized: str | None = None


def _read_field(raw: dict[str, Any]) -> _Field | None:
    ftype = (raw.get("Type") or {}).get("Text")
    if not ftype:
        return None
    value = raw.get("ValueDetection") or {}
    text = value.get("Text")
    if isinstance(text, str):
        text = text.strip() or None
    normalized = (value.get("NormalizedValue") or {}).get("Value")
    confidence = value.get("Confidence")
    if not isinstance(confidence, int | float):
        confidence = (raw.get("Type") or {}).get("Confidence") or 0.0
    return _Field(ftype, text, float(confidence), normalized)


def _pick(fields: list[_Field], types: tuple[str, ...], parse: Any) -> tuple[Any, float] | None:
    """The best parseable field for the first type (in preference order) that has one.

    Within a type, the highest-confidence field wins; Textract often reports the same total
    twice (e.g. "Total" and "Amount due").
    """
    for t in types:
        candidates = sorted(
            (f for f in fields if f.type == t), key=lambda f: f.confidence, reverse=True
        )
        for f in candidates:
            value = parse(f)
            if value is not None:
                return value, round(f.confidence, 2)
    return None


def _merchant(f: _Field) -> str | None:
    if not f.text:
        return None
    name = " ".join(f.text.split())
    # Receipts are often ALL CAPS; "TRADER JOE'S" reads better as "Trader Joe's".
    if name.isupper() and len(name) > 3:
        name = " ".join(w.capitalize() for w in name.split(" "))
    return name or None


def _date(f: _Field) -> date | None:
    if f.normalized:
        d = parse_date(f.normalized[:10])
        if d:
            return d
    return parse_date(f.text)


def _money(f: _Field) -> Decimal | None:
    return parse_money(f.text)


def _line_item(raw: dict[str, Any]) -> ParsedLineItem | None:
    fields = [f for f in map(_read_field, raw.get("LineItemExpenseFields") or []) if f]
    by_type: dict[str, _Field] = {}
    for f in fields:
        if f.text and (f.type not in by_type or f.confidence > by_type[f.type].confidence):
            by_type[f.type] = f

    def text(t: str) -> str | None:
        return by_type[t].text if t in by_type else None

    description = text("ITEM") or text("PRODUCT_CODE")
    amount = parse_money(text("PRICE"))
    unit_price = parse_money(text("UNIT_PRICE"))
    quantity = parse_quantity(text("QUANTITY"))
    if amount is None and unit_price is not None:
        amount = (unit_price * (quantity or 1)).quantize(CENT, rounding=ROUND_HALF_UP)
    if not description and amount is None:
        return None
    return ParsedLineItem(
        description=" ".join((description or "Item").split()),
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
    )


def parse_expense(response: dict[str, Any]) -> ParsedReceipt:
    """Normalize an AnalyzeExpense response. Uses the first expense document only; one upload is
    one receipt."""
    docs = response.get("ExpenseDocuments") or []
    if not docs:
        return ParsedReceipt()
    doc = docs[0]
    fields = [f for f in map(_read_field, doc.get("SummaryFields") or []) if f]

    receipt = ParsedReceipt()
    for name, types, parser in (
        ("merchant", MERCHANT_TYPES, _merchant),
        ("purchase_date", DATE_TYPES, _date),
        ("subtotal", SUBTOTAL_TYPES, _money),
        ("tax", TAX_TYPES, _money),
        ("tip", TIP_TYPES, _money),
        ("total", TOTAL_TYPES, _money),
    ):
        picked = _pick(fields, types, parser)
        if picked:
            setattr(receipt, name, picked[0])
            receipt.field_confidence[name] = picked[1]

    for group in doc.get("LineItemGroups") or []:
        for raw in group.get("LineItems") or []:
            item = _line_item(raw)
            if item:
                receipt.line_items.append(item)
    return receipt


def needs_review(receipt: ParsedReceipt, threshold: float) -> bool:
    """True if a key field is missing or below `threshold` confidence, or the numbers don't add
    up.

    The arithmetic check runs only when every line item has an amount and tax and total are
    known. A missing tip counts as zero: most receipts have no gratuity line, so requiring one
    would almost never run the check.
    """
    for name in KEY_FIELDS:
        if getattr(receipt, name) is None:
            return True
        if receipt.field_confidence.get(name, 100.0) < threshold:
            return True

    amounts = [li.amount for li in receipt.line_items]
    if amounts and all(a is not None for a in amounts) and receipt.tax is not None:
        assert receipt.total is not None
        computed = sum(amounts, Decimal(0)) + receipt.tax + (receipt.tip or Decimal(0))  # type: ignore[arg-type]
        if abs(computed - receipt.total) > TOTALS_TOLERANCE:
            return True
    return False
