import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Groceries", "#16a34a"),
    ("Dining", "#ea580c"),
    ("Transport", "#2563eb"),
    ("Gas", "#ca8a04"),
    ("Shopping", "#db2777"),
    ("Entertainment", "#9333ea"),
    ("Health", "#dc2626"),
    ("Utilities", "#0891b2"),
    ("Travel", "#4f46e5"),
    ("Other", "#6b7280"),
]


def seed_default_categories(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.add_all(
        Category(user_id=user_id, name=name, color=color, is_default=True)
        for name, color in DEFAULT_CATEGORIES
    )
