"""Keyset (cursor) pagination for receipts sorted by a nullable column, newest first."""

import base64
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, and_, or_, tuple_

from app.models import Receipt

SortKey = Literal["purchase_date", "total"]


class InvalidCursor(ValueError):
    pass


def _column(sort: SortKey) -> Any:
    return Receipt.purchase_date if sort == "purchase_date" else Receipt.total


def _parse_value(sort: SortKey, raw: str | None) -> date | Decimal | None:
    if raw is None:
        return None
    return date.fromisoformat(raw) if sort == "purchase_date" else Decimal(raw)


def encode_cursor(sort: SortKey, receipt: Receipt) -> str:
    value = getattr(receipt, sort)
    payload = {
        "s": sort,
        "v": None if value is None else str(value),
        "c": receipt.created_at.isoformat(),
        "i": str(receipt.id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def apply_page(stmt: Select[Any], sort: SortKey, cursor: str | None) -> Select[Any]:
    """Order by `sort` DESC NULLS LAST, then created_at and id DESC; resume after `cursor`."""
    col = _column(sort)
    stmt = stmt.order_by(col.desc().nulls_last(), Receipt.created_at.desc(), Receipt.id.desc())
    if not cursor:
        return stmt
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["s"] != sort:
            raise InvalidCursor("Cursor does not match sort order")
        value = _parse_value(sort, payload["v"])
        created_at = datetime.fromisoformat(payload["c"])
        rid = uuid.UUID(payload["i"])
    except InvalidCursor:
        raise
    except (ValueError, KeyError, TypeError, ArithmeticError) as e:
        raise InvalidCursor("Invalid cursor") from e

    after_tie = tuple_(Receipt.created_at, Receipt.id) < tuple_(created_at, rid)
    if value is None:
        return stmt.where(and_(col.is_(None), after_tie))
    return stmt.where(or_(col < value, and_(col == value, after_tie), col.is_(None)))
