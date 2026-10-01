"""SQS consumer: the production extraction pipeline.

    python -m app.worker

Messages are either S3 ObjectCreated notifications (a receipt finished uploading) or
{"type": "reprocess", "receipt_id": ...} sent by the API. Each is handled idempotently:
receipts already `ready` are skipped, and a per-receipt Postgres advisory lock keeps two
workers from extracting the same receipt (and paying Textract twice) when SQS delivers a
message more than once.

A message is deleted only after it's handled. If handling raises (database down, a bug), the
message reappears after the visibility timeout and, after the queue's maxReceiveCount, moves
to the dead-letter queue. Extraction failures don't raise: they mark the receipt `failed`
with a message for the user, who can reprocess it.
"""

import asyncio
import contextlib
import json
import logging
import re
import signal
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import unquote_plus

import boto3
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.models import Receipt, ReceiptStatus
from app.services.alerts import build_mailer
from app.services.dispatch import REPROCESS
from app.services.processing import Pipeline, process_receipt
from app.services.ratelimit import prune
from app.services.storage import build_storage
from app.services.textract import build_extractor

logger = logging.getLogger("app.worker")

KEY_RE = re.compile(
    r"^users/(?P<user>[0-9a-f-]{36})/receipts/(?P<receipt>[0-9a-f-]{36})\.(jpg|png|pdf)$"
)
WAIT_SECONDS = 20  # SQS long polling
BATCH = 5
PRUNE_EVERY_SECONDS = 3600


class BadMessage(ValueError):
    """Unparseable or unexpected message: left on the queue so it ends up in the DLQ."""


@contextlib.asynccontextmanager
async def receipt_lock(engine: AsyncEngine, receipt_id: uuid.UUID) -> AsyncIterator[bool]:
    """Try to take a session-level advisory lock for this receipt on a dedicated connection
    (held across the commits processing makes). Yields whether it was acquired."""
    key = uuid.UUID(str(receipt_id)).int & 0x7FFF_FFFF_FFFF_FFFF  # fits a signed bigint
    async with engine.connect() as conn:
        acquired = bool(await conn.scalar(select(func.pg_try_advisory_lock(key))))
        try:
            yield acquired
        finally:
            if acquired:
                await conn.scalar(select(func.pg_advisory_unlock(key)))
            await conn.commit()


def parse_message(body: str) -> list[tuple[str, uuid.UUID, uuid.UUID | None]]:
    """-> [(kind, receipt_id, user_id_from_key)]; kind is "upload" or "reprocess".
    An empty list means "nothing to do" (e.g. S3's test event)."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise BadMessage("Body is not JSON") from e
    if not isinstance(data, dict):
        raise BadMessage("Body is not a JSON object")
    if data.get("Event") == "s3:TestEvent":
        return []
    if data.get("type") == REPROCESS:
        try:
            return [("reprocess", uuid.UUID(str(data["receipt_id"])), None)]
        except (KeyError, ValueError) as e:
            raise BadMessage("Reprocess message without a valid receipt_id") from e
    if "Records" in data:
        out = []
        for record in data["Records"]:
            if not str(record.get("eventName", "")).startswith("ObjectCreated"):
                continue
            key = unquote_plus(record.get("s3", {}).get("object", {}).get("key", ""))
            m = KEY_RE.match(key)
            if not m:
                logger.warning("Ignoring object outside the receipts layout: %s", key)
                continue
            out.append(("upload", uuid.UUID(m["receipt"]), uuid.UUID(m["user"])))
        return out
    raise BadMessage("Unrecognized message")


async def handle(
    kind: str,
    receipt_id: uuid.UUID,
    key_user_id: uuid.UUID | None,
    session_factory: Callable[[], AsyncSession],
    engine: AsyncEngine,
    pipeline: Pipeline,
) -> str:
    """Process one receipt if it needs it. Returns what happened (for logs and tests)."""
    async with receipt_lock(engine, receipt_id) as acquired:
        if not acquired:
            return "locked"  # another worker has it right now
        async with session_factory() as session:
            receipt = await session.scalar(
                select(Receipt).where(Receipt.id == receipt_id).with_for_update()
            )
            if receipt is None:
                return "missing"  # deleted before we got to it
            if key_user_id is not None and receipt.user_id != key_user_id:
                logger.error("S3 key owner does not match receipt %s; ignoring", receipt_id)
                return "mismatch"
            if receipt.status == ReceiptStatus.ready:
                return "already-ready"  # duplicate delivery
            if receipt.status == ReceiptStatus.failed:
                return "failed-skip"  # only an explicit reprocess retries a failure
            if kind == "upload" and receipt.status == ReceiptStatus.pending_upload:
                # The S3 event can beat the browser's /complete call; the upload exists, go.
                receipt.status = ReceiptStatus.processing
                await session.commit()
            elif receipt.status != ReceiptStatus.processing:
                return f"skip-{receipt.status.value}"
            else:
                await session.commit()
        await process_receipt(receipt_id, session_factory, pipeline)
        return "processed"


class Worker:
    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], AsyncSession],
        engine: AsyncEngine,
        pipeline: Pipeline,
        sqs: Any | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.engine = engine
        self.pipeline = pipeline
        self.sqs = sqs or boto3.client("sqs", region_name=settings.aws_region)
        self.stopping = asyncio.Event()

    async def handle_message(self, message: dict[str, Any]) -> bool:
        """Handle one SQS message; delete it on success. Returns whether it was deleted."""
        msg_id = message.get("MessageId")
        try:
            for kind, receipt_id, user_id in parse_message(message["Body"]):
                outcome = await handle(
                    kind, receipt_id, user_id, self.session_factory, self.engine, self.pipeline
                )
                logger.info(
                    "Handled message",
                    extra={"message_id": msg_id, "receipt_id": str(receipt_id), "outcome": outcome},
                )
        except Exception:
            logger.exception(
                "Message failed; leaving it for retry/DLQ", extra={"message_id": msg_id}
            )
            return False
        await asyncio.to_thread(
            self.sqs.delete_message,
            QueueUrl=self.settings.sqs_queue_url,
            ReceiptHandle=message["ReceiptHandle"],
        )
        return True

    async def poll_once(self, wait_seconds: int = WAIT_SECONDS) -> int:
        resp = await asyncio.to_thread(
            self.sqs.receive_message,
            QueueUrl=self.settings.sqs_queue_url,
            MaxNumberOfMessages=BATCH,
            WaitTimeSeconds=wait_seconds,
        )
        messages = resp.get("Messages", [])
        await asyncio.gather(*(self.handle_message(m) for m in messages))
        return len(messages)

    async def run(self) -> None:
        logger.info("Worker started", extra={"queue": self.settings.sqs_queue_url})
        last_prune = 0.0
        loop = asyncio.get_running_loop()
        while not self.stopping.is_set():
            try:
                await self.poll_once()
                if loop.time() - last_prune > PRUNE_EVERY_SECONDS:
                    async with self.session_factory() as session:
                        await prune(session)
                    last_prune = loop.time()
            except Exception:
                logger.exception("Polling failed; backing off")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stopping.wait(), timeout=5)
        logger.info("Worker stopped")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_format, settings.log_level)
    if not settings.sqs_queue_url:
        raise SystemExit("SQS_QUEUE_URL is not set")

    from app.db import SessionLocal, engine

    pipeline = Pipeline(
        storage=build_storage(settings),
        extractor=build_extractor(settings),
        threshold=settings.low_confidence_threshold,
        mailer=build_mailer(settings),
        app_base_url=settings.app_base_url,
    )
    worker = Worker(settings, SessionLocal, engine, pipeline)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Finish in-flight messages, then exit (ECS sends SIGTERM before stopping a task).
        loop.add_signal_handler(sig, worker.stopping.set)
    await worker.run()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
