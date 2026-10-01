"""CSV export tuned to open cleanly in Excel and Google Sheets."""

import csv
import io
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

COLUMNS = ["date", "merchant", "category", "subtotal", "tax", "tip", "total", "tags", "notes"]
# Excel needs a byte-order mark to read UTF-8 (otherwise "Café" shows as "CafÃ©").
BOM = "﻿"
# A cell starting with one of these is run as a formula by spreadsheet apps.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str | None) -> str:
    """Neutralize CSV formula injection in free text (merchant names, notes, tags)."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


def csv_row(
    purchase_date: date | None,
    merchant: str | None,
    category: str | None,
    subtotal: Decimal | None,
    tax: Decimal | None,
    tip: Decimal | None,
    total: Decimal | None,
    tags: list[str],
    notes: str | None,
) -> list[str]:
    return [
        purchase_date.isoformat() if purchase_date else "",
        safe_text(merchant),
        safe_text(category),
        _money(subtotal),
        _money(tax),
        _money(tip),
        _money(total),
        safe_text("; ".join(tags)),
        # Keep notes on one line; embedded newlines are legal CSV but trip up some importers.
        safe_text(" ".join((notes or "").split())),
    ]


def _write(rows: Iterable[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue()


def csv_header() -> str:
    """BOM + header row. CRLF line endings throughout, which Excel expects."""
    return BOM + _write([COLUMNS])


def csv_rows(rows: Iterable[list[str]]) -> str:
    return _write(rows)
