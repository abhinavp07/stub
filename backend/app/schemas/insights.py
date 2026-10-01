import uuid
from decimal import Decimal

from pydantic import BaseModel


class SummaryOut(BaseModel):
    month: str
    currency: str
    total: Decimal
    receipt_count: int
    previous_month: str
    previous_total: Decimal
    previous_receipt_count: int
    # Percent change vs the previous month, or null when the previous month had no spending.
    change_pct: Decimal | None
    needs_review_count: int


class CategoryTotalOut(BaseModel):
    category_id: uuid.UUID | None
    name: str
    color: str
    total: Decimal
    receipt_count: int


class ByCategoryOut(BaseModel):
    currency: str
    total: Decimal
    items: list[CategoryTotalOut]


class TrendCategoryOut(BaseModel):
    category_id: uuid.UUID | None
    total: Decimal


class TrendPointOut(BaseModel):
    month: str
    total: Decimal
    receipt_count: int
    by_category: list[TrendCategoryOut] | None = None


class TrendOut(BaseModel):
    currency: str
    months: list[TrendPointOut]
