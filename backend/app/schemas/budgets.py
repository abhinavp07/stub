import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

BudgetStatus = Literal["ok", "warning", "over"]


class BudgetIn(BaseModel):
    monthly_limit: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)


class BudgetOut(BaseModel):
    category_id: uuid.UUID
    category_name: str
    color: str
    monthly_limit: Decimal
    alert_threshold_pct: int
    month: str
    spent: Decimal
    remaining: Decimal
    percent_used: Decimal
    # ok below the alert threshold, warning from the threshold up to 100%, over above 100%.
    status: BudgetStatus
