"""global merchant rules

Global rules name a category ("Groceries") instead of pointing at one, because categories are
per-user. Seeds rules for common merchants.

Revision ID: db6313b997ee
Revises: ad571057f177
Create Date: 2026-10-01 14:46:19.110764

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "db6313b997ee"
down_revision: str | None = "ad571057f177"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Patterns are already normalized (see app.services.categorize.normalize_merchant). Frozen here
# rather than imported so this migration never changes after it ships.
GLOBAL_RULES: dict[str, list[str]] = {
    "Groceries": [
        "kroger",
        "safeway",
        "whole foods",
        "trader joes",
        "aldi",
        "publix",
        "wegmans",
        "heb",
        "food lion",
        "giant eagle",
        "sprouts",
        "meijer",
        "albertsons",
    ],
    "Dining": [
        "starbucks",
        "mcdonalds",
        "chipotle",
        "subway",
        "dunkin",
        "chick fil a",
        "taco bell",
        "panera",
        "dominos",
        "wendys",
        "burger king",
        "uber eats",
        "doordash",
        "grubhub",
    ],
    "Transport": ["uber", "lyft", "amtrak", "metro", "parking"],
    "Gas": ["shell", "chevron", "exxon", "mobil", "bp", "sunoco", "valero", "marathon", "circle k"],
    "Shopping": [
        "walmart",
        "target",
        "costco",
        "amazon",
        "best buy",
        "home depot",
        "lowes",
        "ikea",
        "macys",
        "tj maxx",
    ],
    "Entertainment": ["netflix", "spotify", "amc", "regal", "steam", "ticketmaster"],
    "Health": ["cvs", "walgreens", "rite aid", "pharmacy"],
    "Utilities": ["comcast", "xfinity", "verizon", "att", "t mobile", "pge"],
    "Travel": [
        "delta",
        "united airlines",
        "american airlines",
        "southwest",
        "marriott",
        "hilton",
        "airbnb",
        "expedia",
    ],
}

rules = sa.table(
    "merchant_category_rules",
    sa.column("id", sa.UUID()),
    sa.column("user_id", sa.UUID()),
    sa.column("merchant_pattern", sa.Text()),
    sa.column("category_name", sa.Text()),
)


def upgrade() -> None:
    op.add_column("merchant_category_rules", sa.Column("category_name", sa.Text(), nullable=True))
    op.alter_column(
        "merchant_category_rules", "category_id", existing_type=sa.UUID(), nullable=True
    )
    op.create_check_constraint(
        "user_rule_has_id_global_rule_has_name",
        "merchant_category_rules",
        "(user_id IS NOT NULL AND category_id IS NOT NULL AND category_name IS NULL)"
        " OR (user_id IS NULL AND category_id IS NULL AND category_name IS NOT NULL)",
    )
    op.bulk_insert(
        rules,
        [
            {"id": uuid.uuid4(), "user_id": None, "merchant_pattern": p, "category_name": name}
            for name, patterns in GLOBAL_RULES.items()
            for p in patterns
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM merchant_category_rules WHERE user_id IS NULL")
    op.drop_constraint("user_rule_has_id_global_rule_has_name", "merchant_category_rules")
    op.alter_column(
        "merchant_category_rules", "category_id", existing_type=sa.UUID(), nullable=False
    )
    op.drop_column("merchant_category_rules", "category_name")
