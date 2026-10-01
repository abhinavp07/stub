import uuid

from sqlalchemy import CHAR, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Money, TimestampedBase


class Budget(TimestampedBase):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    monthly_limit: Mapped[Money]
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="80")


class BudgetAlert(TimestampedBase):
    """One row per alert email sent. The unique key enforces "at most once per category per
    month"; the row is written before the email goes out."""

    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("category_id", "month"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[str] = mapped_column(CHAR(7), nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(Text, nullable=False)  # warning | over
