from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.auth import CurrentUser, SessionDep
from app.schemas.insights import (
    ByCategoryOut,
    CategoryTotalOut,
    SummaryOut,
    TrendCategoryOut,
    TrendOut,
    TrendPointOut,
)
from app.services import insights
from app.services.insights import Month

router = APIRouter(prefix="/insights", tags=["insights"])

MonthParam = Annotated[str | None, Query(description="YYYY-MM; defaults to the current month")]


def parse_month(value: str | None) -> Month:
    if value is None:
        return Month.current()
    try:
        return Month.parse(value)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"month: {e}") from None


@router.get("/summary", response_model=SummaryOut)
async def summary(user: CurrentUser, session: SessionDep, month: MonthParam = None) -> SummaryOut:
    current = parse_month(month)
    previous = current.shift(-1)
    total, count = await insights.month_total(session, user.id, current)
    prev_total, prev_count = await insights.month_total(session, user.id, previous)
    change = None
    if prev_total != 0:
        change = ((total - prev_total) / abs(prev_total) * 100).quantize(Decimal("0.1"))
    return SummaryOut(
        month=str(current),
        currency=user.currency,
        total=total,
        receipt_count=count,
        previous_month=str(previous),
        previous_total=prev_total,
        previous_receipt_count=prev_count,
        change_pct=change,
        needs_review_count=await insights.needs_review_count(session, user.id),
    )


@router.get("/by-category", response_model=ByCategoryOut)
async def by_category(
    user: CurrentUser,
    session: SessionDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> ByCategoryOut:
    """Spending per category between `from` and `to` (inclusive). Both are optional."""
    if from_ and to and from_ > to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "from must be before to")
    end_exclusive = to + timedelta(days=1) if to else None
    rows = await insights.totals_by_category(session, user.id, from_, end_exclusive)
    return ByCategoryOut(
        currency=user.currency,
        total=sum((r.total for r in rows), insights.ZERO),
        items=[CategoryTotalOut(**vars(r)) for r in rows],
    )


@router.get("/trend", response_model=TrendOut)
async def trend(
    user: CurrentUser,
    session: SessionDep,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
    end: Annotated[str | None, Query(description="Last month, YYYY-MM; default current")] = None,
    by_category: bool = False,
) -> TrendOut:
    points = await insights.monthly_trend(session, user.id, parse_month(end), months)
    return TrendOut(
        currency=user.currency,
        months=[
            TrendPointOut(
                month=p.month,
                total=p.total,
                receipt_count=p.receipt_count,
                by_category=[
                    TrendCategoryOut(category_id=cid, total=t) for cid, t in p.by_category.items()
                ]
                if by_category
                else None,
            )
            for p in points
        ],
    )
