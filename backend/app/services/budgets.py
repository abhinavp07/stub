from decimal import ROUND_HALF_UP, Decimal

from app.schemas.budgets import BudgetStatus


def percent_used(spent: Decimal, limit: Decimal) -> Decimal:
    return (spent / limit * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def budget_status(spent: Decimal, limit: Decimal, threshold_pct: int) -> BudgetStatus:
    """Amber ("warning") at the alert threshold, red ("over") only above 100%."""
    if spent > limit:
        return "over"
    if spent * 100 >= limit * threshold_pct:
        return "warning"
    return "ok"
