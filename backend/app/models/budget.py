import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
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
