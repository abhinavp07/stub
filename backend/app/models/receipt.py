import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Money, TimestampedBase


class ReceiptStatus(enum.StrEnum):
    pending_upload = "pending_upload"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Receipt(TimestampedBase):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_user_purchase_date", "user_id", text("purchase_date DESC")),
        Index("ix_receipts_user_category", "user_id", "category_id"),
        Index(
            "ix_receipts_merchant_trgm",
            "merchant",
            postgresql_using="gin",
            postgresql_ops={"merchant": "gin_trgm_ops"},
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus, name="receipt_status"),
        nullable=False,
        default=ReceiptStatus.pending_upload,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    merchant: Mapped[str | None] = mapped_column(Text)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Money | None]
    tax: Mapped[Money | None]
    tip: Mapped[Money | None]
    total: Mapped[Money | None]
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="USD")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    field_confidence: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    raw_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    user_edited_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )

    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="LineItem.position",
    )


class LineItem(TimestampedBase):
    __tablename__ = "line_items"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Money | None]
    amount: Mapped[Money | None]

    receipt: Mapped[Receipt] = relationship(back_populates="line_items")
