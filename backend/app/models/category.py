import uuid

from sqlalchemy import Boolean, ForeignKey, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Category(TimestampedBase):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())


class MerchantCategoryRule(TimestampedBase):
    __tablename__ = "merchant_category_rules"
    # NULLS NOT DISTINCT so two global rules (user_id NULL) can't share a pattern.
    __table_args__ = (
        UniqueConstraint("user_id", "merchant_pattern", postgresql_nulls_not_distinct=True),
    )

    # NULL user_id = global rule.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    merchant_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
