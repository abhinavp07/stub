import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, SessionDep
from app.models import Category, Receipt, User
from app.schemas.categories import CategoryCreate, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])

NOT_FOUND = "Category not found"
DUPLICATE = "You already have a category with that name"


async def _get_owned(session: AsyncSession, user: User, category_id: uuid.UUID) -> Category:
    category = await session.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return category


async def _ensure_unique_name(
    session: AsyncSession, user: User, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(Category.id).where(
        Category.user_id == user.id, func.lower(Category.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(Category.id != exclude)
    if await session.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE)


async def _out(session: AsyncSession, category: Category) -> CategoryOut:
    count = await session.scalar(
        select(func.count()).select_from(Receipt).where(Receipt.category_id == category.id)
    )
    return CategoryOut.model_validate(category).model_copy(update={"receipt_count": count or 0})


@router.get("", response_model=list[CategoryOut])
async def list_categories(user: CurrentUser, session: SessionDep) -> list[CategoryOut]:
    counts = (
        select(Receipt.category_id, func.count().label("n"))
        .where(Receipt.user_id == user.id)
        .group_by(Receipt.category_id)
        .subquery()
    )
    rows = await session.execute(
        select(Category, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.category_id == Category.id)
        .where(Category.user_id == user.id)
        .order_by(func.lower(Category.name))
    )
    return [CategoryOut.model_validate(c).model_copy(update={"receipt_count": n}) for c, n in rows]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate, user: CurrentUser, session: SessionDep
) -> CategoryOut:
    await _ensure_unique_name(session, user, body.name)
    category = Category(user_id=user.id, name=body.name, color=body.color, is_default=False)
    session.add(category)
    await session.commit()
    return CategoryOut.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID, body: CategoryUpdate, user: CurrentUser, session: SessionDep
) -> CategoryOut:
    category = await _get_owned(session, user, category_id)
    if body.name is not None:
        await _ensure_unique_name(session, user, body.name, exclude=category.id)
        category.name = body.name
    if body.color is not None:
        category.color = body.color
    await session.commit()
    return await _out(session, category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    """Receipts in the category become uncategorized (FK ON DELETE SET NULL); its budget and
    the user's merchant rules pointing at it are removed (ON DELETE CASCADE)."""
    category = await _get_owned(session, user, category_id)
    await session.delete(category)
    await session.commit()
