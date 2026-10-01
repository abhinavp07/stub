import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.auth import CurrentUser, SessionDep, SettingsDep
from app.models import Budget, Category
from app.routers.insights import MonthParam, parse_month
from app.schemas.budgets import BudgetIn, BudgetOut
from app.services.alerts import Mailer, check_budget_alerts_task, get_mailer
from app.services.budgets import budget_status, percent_used
from app.services.insights import ZERO, Month, spent_by_category

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _out(budget: Budget, category: Category, spent: Decimal | None, month: Month) -> BudgetOut:
    spent_d = spent if spent is not None else ZERO
    return BudgetOut(
        category_id=category.id,
        category_name=category.name,
        color=category.color,
        monthly_limit=budget.monthly_limit,
        alert_threshold_pct=budget.alert_threshold_pct,
        month=str(month),
        spent=spent_d,
        remaining=budget.monthly_limit - spent_d,
        percent_used=percent_used(spent_d, budget.monthly_limit),
        status=budget_status(spent_d, budget.monthly_limit, budget.alert_threshold_pct),
    )


@router.get("", response_model=list[BudgetOut])
async def list_budgets(
    user: CurrentUser, session: SessionDep, month: MonthParam = None
) -> list[BudgetOut]:
    """Every budget with what's been spent in its category this month (or `month`)."""
    current = parse_month(month)
    spent = await spent_by_category(session, user.id, current)
    rows = await session.execute(
        select(Budget, Category)
        .join(Category, Category.id == Budget.category_id)
        .where(Budget.user_id == user.id)
        .order_by(func.lower(Category.name))
    )
    return [_out(b, c, spent.get(c.id), current) for b, c in rows.all()]


@router.put("/{category_id}", response_model=BudgetOut)
async def set_budget(
    category_id: uuid.UUID,
    body: BudgetIn,
    tasks: BackgroundTasks,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> BudgetOut:
    category = await session.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    await session.execute(
        insert(Budget)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            category_id=category.id,
            monthly_limit=body.monthly_limit,
            alert_threshold_pct=body.alert_threshold_pct,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "category_id"],
            set_={
                "monthly_limit": body.monthly_limit,
                "alert_threshold_pct": body.alert_threshold_pct,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()
    budget = await session.scalar(
        select(Budget)
        .where(Budget.user_id == user.id, Budget.category_id == category.id)
        .execution_options(populate_existing=True)
    )
    assert budget is not None
    current = Month.current()
    spent = await spent_by_category(session, user.id, current)
    # Lowering a limit can put this month over the threshold.
    tasks.add_task(check_budget_alerts_task, user.id, mailer, settings.app_base_url)
    return _out(budget, category, spent.get(category.id), current)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(category_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    budget = await session.scalar(
        select(Budget).where(Budget.user_id == user.id, Budget.category_id == category_id)
    )
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    await session.delete(budget)
    await session.commit()
