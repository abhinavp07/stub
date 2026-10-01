import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.auth import CurrentUser, SessionDep
from app.db import SessionLocal
from app.models import Category, Receipt, ReceiptStatus
from app.services.export import csv_header, csv_row, csv_rows
from app.services.pdf_report import MAX_ATTACHMENTS, ReportReceipt, build_report
from app.services.storage import Storage, get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["export"])

BATCH = 500


@router.get("/csv")
async def export_csv(
    user: CurrentUser,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    category_id: Annotated[
        uuid.UUID | Literal["none"] | None,
        Query(description='A category id, or "none" for uncategorized'),
    ] = None,
) -> StreamingResponse:
    """One row per ready receipt, oldest first, streamed so large exports stay cheap."""
    if from_ and to and from_ > to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "from must be before to")

    stmt = (
        select(
            Receipt.purchase_date,
            Receipt.merchant,
            Category.name,
            Receipt.subtotal,
            Receipt.tax,
            Receipt.tip,
            Receipt.total,
            Receipt.tags,
            Receipt.notes,
        )
        .outerjoin(Category, Category.id == Receipt.category_id)
        .where(Receipt.user_id == user.id, Receipt.status == ReceiptStatus.ready)
        .order_by(Receipt.purchase_date.asc().nulls_last(), Receipt.created_at, Receipt.id)
    )
    if from_:
        stmt = stmt.where(Receipt.purchase_date >= from_)
    if to:
        stmt = stmt.where(Receipt.purchase_date <= to)
    if category_id == "none":
        stmt = stmt.where(Receipt.category_id.is_(None))
    elif category_id is not None:
        stmt = stmt.where(Receipt.category_id == category_id)

    async def body() -> AsyncIterator[str]:
        yield csv_header()
        # Own session: the request-scoped one closes when the handler returns, before streaming.
        async with SessionLocal() as session:
            result = await session.stream(stmt.execution_options(yield_per=BATCH))
            async for batch in result.partitions():
                yield csv_rows(csv_row(*row) for row in batch)

    filename = f"receipts-{datetime.now(UTC).date().isoformat()}.csv"
    return StreamingResponse(
        body(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pdf")
async def export_pdf(
    user: CurrentUser,
    session: SessionDep,
    storage: Annotated[Storage, Depends(get_storage)],
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    category_id: Annotated[
        uuid.UUID | Literal["none"] | None,
        Query(description='A category id, or "none" for uncategorized'),
    ] = None,
) -> Response:
    """A PDF with a summary table and the receipt images, for the given range."""
    if from_ and to and from_ > to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "from must be before to")
    stmt = (
        select(Receipt, Category.name)
        .outerjoin(Category, Category.id == Receipt.category_id)
        .where(Receipt.user_id == user.id, Receipt.status == ReceiptStatus.ready)
        .order_by(Receipt.purchase_date.asc().nulls_last(), Receipt.created_at, Receipt.id)
    )
    if from_:
        stmt = stmt.where(Receipt.purchase_date >= from_)
    if to:
        stmt = stmt.where(Receipt.purchase_date <= to)
    if category_id == "none":
        stmt = stmt.where(Receipt.category_id.is_(None))
    elif category_id is not None:
        stmt = stmt.where(Receipt.category_id == category_id)

    rows = (await session.execute(stmt)).all()
    items: list[ReportReceipt] = []
    for i, (receipt, category) in enumerate(rows):
        data = None
        if i < MAX_ATTACHMENTS:
            try:
                data = await storage.read_bytes(receipt.s3_key)
            except Exception:
                logger.warning(
                    "Receipt file missing for PDF report", extra={"receipt_id": str(receipt.id)}
                )
        items.append(
            ReportReceipt(
                purchase_date=receipt.purchase_date,
                merchant=receipt.merchant,
                category=category,
                total=receipt.total,
                content_type=receipt.content_type,
                file=data,
            )
        )
    today = datetime.now(UTC).date()
    pdf = await asyncio.to_thread(
        build_report,
        items,
        currency=user.currency,
        date_from=from_,
        date_to=to,
        generated=today,
        owner=user.display_name or user.email,
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receipt-report-{today}.pdf"'},
    )
