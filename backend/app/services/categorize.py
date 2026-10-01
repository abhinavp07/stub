"""Merchant -> category rules: the user's own rules first, then global ones."""

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, MerchantCategoryRule

# Dropped wherever they appear as whole words: legal suffixes and store-ish noise.
_SUFFIXES = {
    "inc", "llc", "ltd", "co", "corp", "corporation", "company", "store", "stores",
    "supermarket", "the", "com", "www", "no",
}  # fmt: skip


def normalize_merchant(name: str | None) -> str:
    """Lowercase, strip punctuation, store numbers and suffixes.

    "Trader Joe's #552" -> "trader joes"; "SHELL OIL 57442" -> "shell oil";
    "Chick-fil-A, Inc." -> "chick fil a"; "AT&T" -> "att"; "Amazon.com" -> "amazon".
    """
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"['’&]", "", s)  # joined, so "joe's" -> "joes" and "at&t" -> "att"
    s = re.sub(r"#\s*\w+", " ", s)  # "#1234", "# 12a"
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = [w for w in s.split() if not w.isdigit() and w not in _SUFFIXES]
    return " ".join(words)


def best_match(normalized: str, patterns: Iterable[str]) -> str | None:
    """The longest pattern that appears in `normalized` as whole words, so "uber eats" beats
    "uber" and "shell" doesn't match "shellfish shack"."""
    if not normalized:
        return None
    padded = f" {normalized} "
    hits = [p for p in patterns if p and f" {p} " in padded]
    return max(hits, key=len) if hits else None


async def categorize(
    session: AsyncSession, user_id: uuid.UUID, merchant: str | None
) -> uuid.UUID | None:
    """The category for `merchant`, or None if no rule matches."""
    normalized = normalize_merchant(merchant)
    if not normalized:
        return None

    user_rows = await session.execute(
        select(MerchantCategoryRule.merchant_pattern, MerchantCategoryRule.category_id).where(
            MerchantCategoryRule.user_id == user_id
        )
    )
    user_rules = dict(user_rows.all())
    if (hit := best_match(normalized, user_rules)) is not None:
        return user_rules[hit]

    global_rows = await session.execute(
        select(MerchantCategoryRule.merchant_pattern, MerchantCategoryRule.category_name).where(
            MerchantCategoryRule.user_id.is_(None)
        )
    )
    global_rules = dict(global_rows.all())
    if (hit := best_match(normalized, global_rules)) is None:
        return None
    category_name = global_rules[hit]
    assert category_name is not None
    # The user may have renamed or deleted the default category; then there's no match.
    return await session.scalar(
        select(Category.id).where(
            Category.user_id == user_id, func.lower(Category.name) == category_name.lower()
        )
    )


async def learn_rule(
    session: AsyncSession, user_id: uuid.UUID, merchant: str | None, category_id: uuid.UUID
) -> None:
    """Remember that this user files this merchant under this category."""
    pattern = normalize_merchant(merchant)
    if not pattern:
        return
    stmt = insert(MerchantCategoryRule).values(
        id=uuid.uuid4(), user_id=user_id, merchant_pattern=pattern, category_id=category_id
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "merchant_pattern"],
            set_={"category_id": category_id, "updated_at": func.now()},
        )
    )
