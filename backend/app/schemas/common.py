from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

# Sent over JSON as strings (Pydantic's default for Decimal); accepts strings or numbers.
MoneyIn = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
QuantityIn = Annotated[Decimal, Field(max_digits=12, decimal_places=3, gt=0)]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
