import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Annotated[Decimal, mapped_column(Numeric(12, 2))]


class Base(DeclarativeBase):
    pass


class TimestampedBase(Base):
    """Every table gets a UUID primary key plus UTC created_at/updated_at."""

    __abstract__ = True
    # Fetch server-generated timestamps via RETURNING so they never need a lazy load, which
    # async sessions can't do.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
