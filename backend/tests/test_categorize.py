import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import MerchantCategoryRule
from app.services.categorize import best_match, normalize_merchant
from app.services.defaults import DEFAULT_CATEGORIES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Trader Joe's #552", "trader joes"),
        ("SHELL OIL 57442", "shell oil"),
        ("Chick-fil-A, Inc.", "chick fil a"),
        ("AT&T", "att"),
        ("Amazon.com", "amazon"),
        ("The Home Depot #0601", "home depot"),
        ("Joe's Diner LLC", "joes diner"),
        ("WALMART SUPERCENTER STORE # 1234", "walmart supercenter"),
        ("  ", ""),
        (None, ""),
    ],
)
def test_normalize_merchant(raw: str | None, expected: str) -> None:
    assert normalize_merchant(raw) == expected


def test_best_match_prefers_longest_whole_word_pattern() -> None:
    patterns = ["uber", "uber eats", "shell"]
    assert best_match("uber eats", patterns) == "uber eats"
    assert best_match("uber trip help", patterns) == "uber"
    assert best_match("shell oil", patterns) == "shell"
    assert best_match("shellfish shack", patterns) is None
    assert best_match("", patterns) is None


async def test_seeded_global_rules_are_normalized_and_use_default_categories() -> None:
    async with SessionLocal() as s:
        rules = list(
            await s.scalars(
                select(MerchantCategoryRule).where(MerchantCategoryRule.user_id.is_(None))
            )
        )
    assert len(rules) >= 40
    names = {name for name, _ in DEFAULT_CATEGORIES}
    for rule in rules:
        assert normalize_merchant(rule.merchant_pattern) == rule.merchant_pattern
        assert rule.category_name in names
        assert rule.category_id is None
