import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category

# Colors are the validated categorical palette in its fixed slot order (CVD-checked for
# adjacent marks). Eight hues is the ceiling for a categorical palette, so Travel gets a darker
# blue step and Other a neutral gray; charts always pair color with a visible name.
DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Groceries", "#2a78d6"),
    ("Dining", "#eb6834"),
    ("Transport", "#1baf7a"),
    ("Gas", "#eda100"),
    ("Shopping", "#e87ba4"),
    ("Entertainment", "#008300"),
    ("Health", "#4a3aa7"),
    ("Utilities", "#e34948"),
    ("Travel", "#184f95"),
    ("Other", "#8a8984"),
]


def seed_default_categories(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.add_all(
        Category(user_id=user_id, name=name, color=color, is_default=True)
        for name, color in DEFAULT_CATEGORIES
    )
