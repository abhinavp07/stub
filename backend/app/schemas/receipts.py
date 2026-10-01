import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import ReceiptStatus
from app.schemas.common import MoneyIn, QuantityIn


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)


class UploadUrlResponse(BaseModel):
    receipt_id: uuid.UUID
    upload_url: str
    fields: dict[str, str]


class LineItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: QuantityIn | None = None
    unit_price: MoneyIn | None = None
    amount: MoneyIn | None = None


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


class ReceiptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ReceiptStatus
    error_message: str | None
    original_filename: str
    content_type: str
    merchant: str | None
    purchase_date: date | None
    total: Decimal | None
    currency: str
    category_id: uuid.UUID | None
    tags: list[str]
    needs_review: bool
    created_at: datetime
    thumbnail_url: str | None = None


class ReceiptDetail(ReceiptSummary):
    subtotal: Decimal | None
    tax: Decimal | None
    tip: Decimal | None
    notes: str | None
    field_confidence: dict[str, float]
    user_edited_fields: list[str]
    line_items: list[LineItemOut]
    updated_at: datetime
    image_url: str | None = None
    # Extracted fields below LOW_CONFIDENCE_THRESHOLD that the user hasn't corrected yet.
    low_confidence_fields: list[str] = []


class ReceiptUpdate(BaseModel):
    """Every field is optional; only the fields sent are changed. Send null to clear one."""

    model_config = ConfigDict(extra="forbid")

    merchant: str | None = Field(default=None, max_length=200)
    purchase_date: date | None = None
    subtotal: MoneyIn | None = None
    tax: MoneyIn | None = None
    tip: MoneyIn | None = None
    total: MoneyIn | None = None
    category_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)
    tags: list[Annotated[str, Field(max_length=40)]] | None = Field(default=None, max_length=50)
    # Send false to confirm the receipt has been reviewed.
    needs_review: bool | None = None
