import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import CurrentUser, SessionDep, SettingsDep
from app.config import Settings
from app.models import Category, LineItem, Receipt, ReceiptStatus, User
from app.schemas.common import Page
from app.schemas.receipts import (
    LineItemIn,
    ReceiptDetail,
    ReceiptSummary,
    ReceiptUpdate,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.alerts import Mailer, check_budget_alerts_task, get_mailer
from app.services.categorize import categorize, learn_rule
from app.services.dispatch import Dispatcher, get_dispatcher
from app.services.pagination import InvalidCursor, SortKey, apply_page, encode_cursor
from app.services.processing import CATEGORY_FIELD, LINE_ITEMS_FIELD, SCALAR_FIELDS
from app.services.ratelimit import UPLOAD_PER_USER, RateLimiterDep
from app.services.receipt_filters import ReceiptFilters, receipt_filters
from app.services.storage import (
    ALLOWED_CONTENT_TYPES,
    LocalStorage,
    Storage,
    get_storage,
    receipt_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/receipts", tags=["receipts"])

StorageDep = Annotated[Storage, Depends(get_storage)]
DispatcherDep = Annotated[Dispatcher, Depends(get_dispatcher)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]

NOT_FOUND = "Receipt not found"


async def _get_owned(
    session: AsyncSession,
    user: User,
    receipt_id: uuid.UUID,
    *,
    with_items: bool = False,
    for_update: bool = False,
) -> Receipt:
    """Load a receipt owned by `user`. Someone else's receipt is a 404, not a 403, so its
    existence isn't revealed. `for_update` locks the row so a write can't interleave with
    background processing saving its results."""
    stmt = select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user.id)
    if with_items:
        stmt = stmt.options(selectinload(Receipt.line_items))
    if for_update:
        stmt = stmt.with_for_update(of=Receipt)
    receipt = await session.scalar(stmt)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return receipt


async def _file_url(receipt: Receipt, storage: Storage) -> str | None:
    """Presigned URL in S3 mode; the ownership-checked file endpoint in local mode."""
    if receipt.status == ReceiptStatus.pending_upload:
        return None
    url = await storage.presign_download(receipt.s3_key)
    return url or f"/api/receipts/{receipt.id}/file"


async def _thumbnail_url(receipt: Receipt, storage: Storage) -> str | None:
    """Images only; the list shows an icon for PDFs."""
    if not receipt.content_type.startswith("image/"):
        return None
    return await _file_url(receipt, storage)


async def _detail(receipt: Receipt, storage: Storage, settings: Settings) -> ReceiptDetail:
    image_url = await _file_url(receipt, storage)
    edited = set(receipt.user_edited_fields)
    low = [
        name
        for name, score in (receipt.field_confidence or {}).items()
        if score < settings.low_confidence_threshold and name not in edited
    ]
    return ReceiptDetail.model_validate(receipt).model_copy(
        update={
            "image_url": image_url,
            "thumbnail_url": image_url if receipt.content_type.startswith("image/") else None,
            "low_confidence_fields": low,
        }
    )


@router.post("/upload-url", response_model=UploadUrlResponse, status_code=201)
async def create_upload_url(
    body: UploadUrlRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    limiter: RateLimiterDep,
) -> UploadUrlResponse:
    await limiter.check(UPLOAD_PER_USER, str(user.id))
    if body.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only JPG, PNG and PDF files are supported"
        )
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Files must be {settings.max_upload_mb} MB or smaller"
        )

    receipt_id = uuid.uuid4()
    key = receipt_key(user.id, receipt_id, body.content_type)
    session.add(
        Receipt(
            id=receipt_id,
            user_id=user.id,
            s3_key=key,
            original_filename=body.filename,
            content_type=body.content_type,
            status=ReceiptStatus.pending_upload,
            currency=user.currency,
        )
    )
    await session.commit()
    upload = await storage.presign_upload(key, body.content_type, settings.max_upload_bytes)
    return UploadUrlResponse(receipt_id=receipt_id, upload_url=upload.url, fields=upload.fields)


@router.post("/{receipt_id}/complete", response_model=ReceiptDetail)
async def complete_upload(
    receipt_id: uuid.UUID,
    tasks: BackgroundTasks,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    dispatcher: DispatcherDep,
) -> ReceiptDetail:
    """Idempotent: in queue mode the S3 event may already have started processing before the
    browser calls this, and a retried call should just report the current state."""
    receipt = await _get_owned(session, user, receipt_id, with_items=True, for_update=True)
    if receipt.status != ReceiptStatus.pending_upload:
        return await _detail(receipt, storage, settings)
    size = await storage.object_size(receipt.s3_key)
    if size is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload not found. Try uploading again.")
    if size > settings.max_upload_bytes:
        await storage.delete(receipt.s3_key)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Files must be {settings.max_upload_mb} MB or smaller"
        )
    receipt.status = ReceiptStatus.processing
    await session.commit()
    await dispatcher.upload_completed(tasks, receipt.id)
    return await _detail(receipt, storage, settings)


@router.get("", response_model=Page[ReceiptSummary])
async def list_receipts(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    filters: Annotated[ReceiptFilters, Depends(receipt_filters)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    sort: SortKey = "purchase_date",
) -> Page[ReceiptSummary]:
    stmt = select(Receipt).where(
        Receipt.user_id == user.id, Receipt.status != ReceiptStatus.pending_upload
    )
    stmt = filters.apply(stmt)
    try:
        stmt = apply_page(stmt, sort, cursor)
    except InvalidCursor as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    rows = list(await session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page(
        items=[
            ReceiptSummary.model_validate(r).model_copy(
                update={"thumbnail_url": await _thumbnail_url(r, storage)}
            )
            for r in rows
        ],
        next_cursor=encode_cursor(sort, rows[-1]) if has_more else None,
    )


@router.get("/{receipt_id}", response_model=ReceiptDetail)
async def get_receipt(
    receipt_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> ReceiptDetail:
    receipt = await _get_owned(session, user, receipt_id, with_items=True)
    return await _detail(receipt, storage, settings)


@router.get("/{receipt_id}/file", response_model=None)
async def get_receipt_file(
    receipt_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> Response:
    """The receipt's original file. Streams from disk in local mode; redirects to a
    short-lived presigned URL in S3 mode."""
    receipt = await _get_owned(session, user, receipt_id)
    if receipt.status == ReceiptStatus.pending_upload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not uploaded yet")
    if isinstance(storage, LocalStorage):
        path = storage.file_path(receipt.s3_key)
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
        return FileResponse(
            path, media_type=receipt.content_type, headers={"Cache-Control": "private, max-age=300"}
        )
    url = await storage.presign_download(receipt.s3_key)
    if url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.patch("/{receipt_id}", response_model=ReceiptDetail)
async def update_receipt(
    receipt_id: uuid.UUID,
    body: ReceiptUpdate,
    tasks: BackgroundTasks,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    mailer: MailerDep,
) -> ReceiptDetail:
    receipt = await _get_owned(session, user, receipt_id, with_items=True, for_update=True)
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)

    if changes.get("category_id") is not None:
        owned = await session.scalar(
            select(Category.id).where(
                Category.id == changes["category_id"], Category.user_id == user.id
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Category not found")
    if "merchant" in changes and changes["merchant"] is not None:
        changes["merchant"] = changes["merchant"].strip() or None
    if "tags" in changes:
        tags = changes["tags"] or []
        changes["tags"] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))

    edited = list(receipt.user_edited_fields or [])
    tracked = (*SCALAR_FIELDS, CATEGORY_FIELD)
    category_changed = "category_id" in changes and changes["category_id"] != receipt.category_id
    merchant_changed = "merchant" in changes and changes["merchant"] != receipt.merchant
    for name, value in changes.items():
        if name in tracked and value != getattr(receipt, name) and name not in edited:
            edited.append(name)
        setattr(receipt, name, value)
    receipt.user_edited_fields = edited

    if category_changed and receipt.category_id is not None:
        # Learning: the next receipt from this merchant lands in the same category.
        await learn_rule(session, user.id, receipt.merchant, receipt.category_id)
    elif merchant_changed and CATEGORY_FIELD not in edited:
        # The user hasn't picked a category, so re-run the rules for the corrected name.
        receipt.category_id = await categorize(session, user.id, receipt.merchant)

    await session.commit()
    if receipt.status == ReceiptStatus.ready and {"total", "purchase_date", "category_id"} & set(
        changes
    ):
        tasks.add_task(check_budget_alerts_task, user.id, mailer, settings.app_base_url)
    await session.refresh(receipt, ["line_items"])
    return await _detail(receipt, storage, settings)


@router.put("/{receipt_id}/line-items", response_model=ReceiptDetail)
async def replace_line_items(
    receipt_id: uuid.UUID,
    body: Annotated[list[LineItemIn], Body(max_length=500)],
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> ReceiptDetail:
    receipt = await _get_owned(session, user, receipt_id, with_items=True, for_update=True)
    receipt.line_items = [LineItem(position=i, **item.model_dump()) for i, item in enumerate(body)]
    if LINE_ITEMS_FIELD not in receipt.user_edited_fields:
        receipt.user_edited_fields = [*receipt.user_edited_fields, LINE_ITEMS_FIELD]
    await session.commit()
    await session.refresh(receipt, ["line_items"])
    return await _detail(receipt, storage, settings)


@router.post("/{receipt_id}/reprocess", response_model=ReceiptDetail)
async def reprocess_receipt(
    receipt_id: uuid.UUID,
    tasks: BackgroundTasks,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    dispatcher: DispatcherDep,
) -> ReceiptDetail:
    receipt = await _get_owned(session, user, receipt_id, with_items=True, for_update=True)
    if receipt.status not in (ReceiptStatus.ready, ReceiptStatus.failed):
        raise HTTPException(status.HTTP_409_CONFLICT, "This receipt can't be reprocessed right now")
    receipt.status = ReceiptStatus.processing
    receipt.error_message = None
    await session.commit()
    await dispatcher.reprocess(tasks, receipt.id)
    return await _detail(receipt, storage, settings)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_receipt(
    receipt_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> None:
    receipt = await _get_owned(session, user, receipt_id, for_update=True)
    # File first: if that fails the row stays, so the user can retry and nothing is orphaned.
    try:
        await storage.delete(receipt.s3_key)
    except Exception:
        logger.exception("Failed to delete stored file for receipt %s", receipt.id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Couldn't delete the stored file. Try again."
        ) from None
    await session.delete(receipt)
    await session.commit()
