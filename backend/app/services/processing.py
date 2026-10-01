"""Run extraction for one receipt and save the result."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import LineItem, Receipt, ReceiptStatus
from app.services.alerts import Mailer, check_budget_alerts
from app.services.categorize import categorize
from app.services.insights import Month
from app.services.parsing import ParsedReceipt, needs_review, parse_expense
from app.services.storage import Storage
from app.services.textract import ExtractionError, Extractor

logger = logging.getLogger(__name__)


@dataclass
class Pipeline:
    """Everything extraction needs, shared by the API's in-process path and the SQS worker."""

    storage: Storage
    extractor: Extractor
    threshold: float
    mailer: Mailer | None = None
    app_base_url: str = ""


GENERIC_FAILURE = "Something went wrong while reading this receipt. Try reprocessing it."
SCALAR_FIELDS = ("merchant", "purchase_date", "subtotal", "tax", "tip", "total")
LINE_ITEMS_FIELD = "line_items"
CATEGORY_FIELD = "category_id"


def apply_extraction(
    receipt: Receipt, parsed: ParsedReceipt, raw: dict[str, Any], threshold: float
) -> None:
    """Copy parsed values onto the receipt, leaving anything the user edited untouched."""
    edited = set(receipt.user_edited_fields or [])
    confidence = dict(receipt.field_confidence or {})
    for name in SCALAR_FIELDS:
        if name in edited:
            continue
        setattr(receipt, name, getattr(parsed, name))
        if name in parsed.field_confidence:
            confidence[name] = parsed.field_confidence[name]
        else:
            confidence.pop(name, None)

    if LINE_ITEMS_FIELD not in edited:
        receipt.line_items = [
            LineItem(
                position=i,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                amount=li.amount,
            )
            for i, li in enumerate(parsed.line_items)
        ]

    receipt.field_confidence = confidence
    receipt.raw_extraction = raw
    # Judge the receipt as it will be shown: user-edited values count as fully confident.
    effective = ParsedReceipt(
        **{name: getattr(receipt, name) for name in SCALAR_FIELDS},
        line_items=parsed.line_items if LINE_ITEMS_FIELD not in edited else receipt.line_items,  # type: ignore[arg-type]
        field_confidence={k: v for k, v in confidence.items() if k not in edited},
    )
    receipt.needs_review = needs_review(effective, threshold)


async def process_receipt(
    receipt_id: uuid.UUID,
    session_factory: Callable[[], AsyncSession],
    pipeline: Pipeline,
) -> None:
    """Background task: extract, parse and save. Never raises; failures are recorded on the
    receipt.

    Extraction can take seconds, and the user may edit the receipt meanwhile. So the row is read,
    the transaction ends, extraction runs, and only then is the row re-read under a lock and
    updated, which respects every edit (and user_edited_fields) made in between.
    """
    async with session_factory() as session:
        receipt = await session.get(Receipt, receipt_id)
        if receipt is None or receipt.status != ReceiptStatus.processing:
            return
        key = receipt.s3_key
        await session.commit()
        try:
            doc = await pipeline.storage.document_ref(key)
            raw = await pipeline.extractor.analyze(doc, key)
            parsed = parse_expense(raw)

            receipt = await session.scalar(
                select(Receipt)
                .where(Receipt.id == receipt_id)
                .options(selectinload(Receipt.line_items))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if receipt is None or receipt.status != ReceiptStatus.processing:
                return  # deleted (or otherwise resolved) while extraction ran
            apply_extraction(receipt, parsed, raw, pipeline.threshold)
            if CATEGORY_FIELD not in receipt.user_edited_fields:
                receipt.category_id = await categorize(session, receipt.user_id, receipt.merchant)
            receipt.status = ReceiptStatus.ready
            receipt.error_message = None
            await session.commit()
            user_id, purchase_date = receipt.user_id, receipt.purchase_date
        except Exception as e:
            logger.exception("Processing failed for receipt %s", receipt_id)
            await session.rollback()
            failed = await session.get(Receipt, receipt_id, populate_existing=True)
            if failed is None or failed.status != ReceiptStatus.processing:
                return
            failed.status = ReceiptStatus.failed
            failed.error_message = (
                e.user_message if isinstance(e, ExtractionError) else GENERIC_FAILURE
            )
            await session.commit()
            return

        if pipeline.mailer is not None and purchase_date is not None:
            try:
                await check_budget_alerts(
                    session,
                    user_id,
                    Month.of(purchase_date),
                    pipeline.mailer,
                    pipeline.app_base_url,
                )
            except Exception:
                logger.exception("Budget alert check failed after processing %s", receipt_id)
