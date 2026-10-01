"""Spending aggregates. A receipt counts toward spending when it's ready and has both a
purchase date and a total; everything is bucketed by purchase_date (a calendar date, no
timezone math)."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Receipt, ReceiptStatus

ZERO = Decimal("0.00")
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @classmethod
    def parse(cls, value: str) -> "Month":
        m = _MONTH_RE.match(value)
        if not m:
            raise ValueError("Use the format YYYY-MM")
        return cls(int(m.group(1)), int(m.group(2)))

    @classmethod
    def current(cls) -> "Month":
        today = datetime.now(UTC).date()
        return cls(today.year, today.month)

    @classmethod
    def of(cls, d: date) -> "Month":
        return cls(d.year, d.month)

    def shift(self, n: int) -> "Month":
        index = self.year * 12 + (self.month - 1) + n
        return Month(index // 12, index % 12 + 1)

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def next_first_day(self) -> date:
        return self.shift(1).first_day

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def spending(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Receipts that count as spending for this user."""
    return and_(
        Receipt.user_id == user_id,
        Receipt.status == ReceiptStatus.ready,
        Receipt.total.is_not(None),
        Receipt.purchase_date.is_not(None),
    )


def in_range(start: date | None, end_exclusive: date | None) -> ColumnElement[bool]:
    conds = []
    if start is not None:
        conds.append(Receipt.purchase_date >= start)
    if end_exclusive is not None:
        conds.append(Receipt.purchase_date < end_exclusive)
    return and_(true(), *conds)


async def month_total(
    session: AsyncSession, user_id: uuid.UUID, month: Month
) -> tuple[Decimal, int]:
    row = (
        await session.execute(
            select(func.coalesce(func.sum(Receipt.total), ZERO), func.count()).where(
                spending(user_id), in_range(month.first_day, month.next_first_day)
            )
        )
    ).one()
    return Decimal(row[0]), int(row[1])


async def needs_review_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    n = await session.scalar(
        select(func.count()).where(
            Receipt.user_id == user_id,
            Receipt.status == ReceiptStatus.ready,
            Receipt.needs_review.is_(True),
        )
    )
    return int(n or 0)


@dataclass
class CategoryTotal:
    category_id: uuid.UUID | None
    name: str
    color: str
    total: Decimal
    receipt_count: int


UNCATEGORIZED_NAME = "Uncategorized"
UNCATEGORIZED_COLOR = "#9ca3af"


async def totals_by_category(
    session: AsyncSession, user_id: uuid.UUID, start: date | None, end_exclusive: date | None
) -> list[CategoryTotal]:
    rows = await session.execute(
        select(
            Receipt.category_id,
            Category.name,
            Category.color,
            func.sum(Receipt.total),
            func.count(),
        )
        .outerjoin(Category, Category.id == Receipt.category_id)
        .where(spending(user_id), in_range(start, end_exclusive))
        .group_by(Receipt.category_id, Category.name, Category.color)
    )
    out = [
        CategoryTotal(
            category_id=cid,
            name=name or UNCATEGORIZED_NAME,
            color=color or UNCATEGORIZED_COLOR,
            total=Decimal(total),
            receipt_count=int(n),
        )
        for cid, name, color, total, n in rows.all()
    ]
    return sorted(out, key=lambda c: (-c.total, c.name.lower()))


@dataclass
class TrendPoint:
    month: str
    total: Decimal
    receipt_count: int
    by_category: dict[uuid.UUID | None, Decimal]


async def monthly_trend(
    session: AsyncSession, user_id: uuid.UUID, end: Month, months: int
) -> list[TrendPoint]:
    """`months` consecutive months ending with `end`, oldest first; empty months are zero."""
    start = end.shift(-(months - 1))
    month_col = func.date_trunc("month", Receipt.purchase_date)
    rows = await session.execute(
        select(month_col, Receipt.category_id, func.sum(Receipt.total), func.count())
        .where(spending(user_id), in_range(start.first_day, end.next_first_day))
        .group_by(month_col, Receipt.category_id)
    )
    points = {
        str(start.shift(i)): TrendPoint(str(start.shift(i)), ZERO, 0, {}) for i in range(months)
    }
    for month_start, category_id, total, n in rows.all():
        p = points[str(Month.of(_as_date(month_start)))]
        p.total += Decimal(total)
        p.receipt_count += int(n)
        p.by_category[category_id] = Decimal(total)
    return list(points.values())


def _as_date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


async def spent_by_category(
    session: AsyncSession, user_id: uuid.UUID, month: Month
) -> dict[uuid.UUID, Decimal]:
    rows = await session.execute(
        select(Receipt.category_id, func.sum(Receipt.total))
        .where(
            spending(user_id),
            in_range(month.first_day, month.next_first_day),
            Receipt.category_id.is_not(None),
        )
        .group_by(Receipt.category_id)
    )
    return {cid: Decimal(total) for cid, total in rows.all()}
