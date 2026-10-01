import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Text, UniqueConstraint, false
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
    """Maps a normalized merchant pattern to a category.

    User rules (user_id set) point at one of the user's categories. Global rules (user_id NULL)
    can't, because categories are per-user, so they name a category instead ("Groceries") and
    resolve to the user's category with that name.
    """

    __tablename__ = "merchant_category_rules"
    __table_args__ = (
        # NULLS NOT DISTINCT so two global rules (user_id NULL) can't share a pattern.
        UniqueConstraint("user_id", "merchant_pattern", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            "(user_id IS NOT NULL AND category_id IS NOT NULL AND category_name IS NULL)"
            " OR (user_id IS NULL AND category_id IS NULL AND category_name IS NOT NULL)",
            name="user_rule_has_id_global_rule_has_name",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    merchant_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    category_name: Mapped[str | None] = mapped_column(Text)
