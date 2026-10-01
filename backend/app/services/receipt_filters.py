"""Filters for the receipts list. Every filter is optional and they all combine with AND."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Query
from sqlalchemy import Select

from app.models import Receipt, ReceiptStatus

UNCATEGORIZED = "none"


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class ReceiptFilters:
    q: str | None = None
    category_id: uuid.UUID | Literal["none"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    status: ReceiptStatus | None = None
    needs_review: bool | None = None
    tag: str | None = None

    def apply(self, stmt: Select[Any]) -> Select[Any]:
        if self.q and self.q.strip():
            # Case-insensitive partial match; served by the pg_trgm index on merchant.
            stmt = stmt.where(Receipt.merchant.ilike(f"%{_escape_like(self.q.strip())}%"))
        if self.category_id == UNCATEGORIZED:
            stmt = stmt.where(Receipt.category_id.is_(None))
        elif self.category_id is not None:
            stmt = stmt.where(Receipt.category_id == self.category_id)
        if self.date_from is not None:
            stmt = stmt.where(Receipt.purchase_date >= self.date_from)
        if self.date_to is not None:
            stmt = stmt.where(Receipt.purchase_date <= self.date_to)
        if self.min_total is not None:
            stmt = stmt.where(Receipt.total >= self.min_total)
        if self.max_total is not None:
            stmt = stmt.where(Receipt.total <= self.max_total)
        if self.status is not None:
            stmt = stmt.where(Receipt.status == self.status)
        if self.needs_review is not None:
            stmt = stmt.where(Receipt.needs_review.is_(self.needs_review))
        if self.tag and self.tag.strip():
            stmt = stmt.where(Receipt.tags.contains([self.tag.strip()]))
        return stmt


def receipt_filters(
    q: Annotated[str | None, Query(max_length=200, description="Merchant search")] = None,
    category_id: Annotated[
        uuid.UUID | Literal["none"] | None,
        Query(description='A category id, or "none" for uncategorized'),
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_total: Annotated[Decimal | None, Query(max_digits=12, decimal_places=2)] = None,
    max_total: Annotated[Decimal | None, Query(max_digits=12, decimal_places=2)] = None,
    status: ReceiptStatus | None = None,
    needs_review: bool | None = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
) -> ReceiptFilters:
    return ReceiptFilters(
        q, category_id, date_from, date_to, min_total, max_total, status, needs_review, tag
    )
