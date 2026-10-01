"""Budget alert emails: sent when a category's spending reaches its alert threshold, at most
once per category per month."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

import boto3
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Budget, BudgetAlert, Category, User
from app.services.budgets import budget_status, percent_used
from app.services.insights import Month, spent_by_category

logger = logging.getLogger(__name__)


@dataclass
class Email:
    to: str
    subject: str
    text: str


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


@dataclass
class LogMailer:
    """Development mailer: logs instead of sending, and remembers what it 'sent'."""

    sent: list[Email] = field(default_factory=list)

    async def send(self, email: Email) -> None:
        self.sent.append(email)
        logger.info("Email (not sent, EMAIL_MODE=log) to=%s subject=%r", email.to, email.subject)


class SesMailer:
    def __init__(self, sender: str, region: str, client: Any | None = None) -> None:
        self.sender = sender
        self._ses = client or boto3.client("sesv2", region_name=region)

    async def send(self, email: Email) -> None:
        await asyncio.to_thread(
            self._ses.send_email,
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [email.to]},
            Content={
                "Simple": {
                    "Subject": {"Data": email.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": email.text, "Charset": "UTF-8"}},
                }
            },
        )


def build_mailer(settings: Settings) -> Mailer:
    if settings.email_mode == "ses":
        return SesMailer(settings.email_from, settings.aws_region)
    return LogMailer()


@lru_cache
def _default_mailer() -> Mailer:
    return build_mailer(get_settings())


def get_mailer() -> Mailer:
    """FastAPI dependency; overridden in tests."""
    return _default_mailer()


def _money(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}"


def compose(
    user: User, category: Category, budget: Budget, spent: Decimal, month: Month, base_url: str
) -> Email:
    pct = percent_used(spent, budget.monthly_limit)
    month_name = f"{month.first_day:%B %Y}"
    if spent > budget.monthly_limit:
        subject = f"You're over your {category.name} budget for {month_name}"
        headline = (
            f"You've spent {_money(spent, user.currency)} on {category.name} this month, "
            f"{_money(spent - budget.monthly_limit, user.currency)} over your "
            f"{_money(budget.monthly_limit, user.currency)} budget ({pct}%)."
        )
    else:
        subject = f"You've used {pct}% of your {category.name} budget"
        headline = (
            f"You've spent {_money(spent, user.currency)} of your "
            f"{_money(budget.monthly_limit, user.currency)} {category.name} budget for "
            f"{month_name} ({pct}%), past your {budget.alert_threshold_pct}% alert."
        )
    text = (
        f"Hi {user.display_name or 'there'},\n\n{headline}\n\n"
        f"See your budgets: {base_url.rstrip('/')}/budgets\n\n"
        "You'll get at most one alert per category each month.\n"
    )
    return Email(to=user.email, subject=subject, text=text)


async def check_budget_alerts(
    session: AsyncSession,
    user_id: uuid.UUID,
    month: Month,
    mailer: Mailer,
    base_url: str,
) -> list[Email]:
    """Email the user about any budget that has reached its threshold this month and hasn't
    been alerted yet. Past months are ignored: an alert about last month is just noise.

    The alert row is committed before sending, so a crash or a concurrent check can never
    produce a second email; a failed send is logged, not retried (at most once).
    """
    if month != Month.current():
        return []
    spent = await spent_by_category(session, user_id, month)
    rows = (
        await session.execute(
            select(Budget, Category)
            .join(Category, Category.id == Budget.category_id)
            .where(Budget.user_id == user_id)
        )
    ).all()

    due: list[tuple[Budget, Category, Decimal]] = []
    for budget, category in rows:
        amount = spent.get(category.id, Decimal("0"))
        status = budget_status(amount, budget.monthly_limit, budget.alert_threshold_pct)
        if status == "ok":
            continue
        claimed = await session.scalar(
            insert(BudgetAlert)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                category_id=category.id,
                month=str(month),
                status=status,
            )
            .on_conflict_do_nothing(index_elements=["category_id", "month"])
            .returning(BudgetAlert.id)
        )
        if claimed is not None:
            due.append((budget, category, amount))
    await session.commit()
    if not due:
        return []

    user = await session.get(User, user_id)
    assert user is not None
    sent = []
    for budget, category, amount in due:
        email = compose(user, category, budget, amount, month, base_url)
        try:
            await mailer.send(email)
            sent.append(email)
        except Exception:
            logger.exception("Failed to send budget alert for category %s", category.id)
    return sent


async def check_budget_alerts_task(
    user_id: uuid.UUID, mailer: Mailer, base_url: str, month: Month | None = None
) -> None:
    """Background-task wrapper with its own session; never raises."""
    from app.db import SessionLocal

    try:
        async with SessionLocal() as session:
            await check_budget_alerts(session, user_id, month or Month.current(), mailer, base_url)
    except Exception:
        logger.exception("Budget alert check failed for user %s", user_id)
