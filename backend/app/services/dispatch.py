"""How a receipt gets to the extraction pipeline.

In-process (default, local dev): FastAPI BackgroundTasks run extraction in the API.
Queue (SQS_QUEUE_URL set, production): uploads reach the worker through S3 ObjectCreated
events, so the API never enqueues them itself (that would double-process every upload);
reprocessing has no S3 event, so the API sends its own message.
"""

import asyncio
import json
import uuid
from functools import lru_cache
from typing import Annotated, Any, Protocol

import boto3
from fastapi import BackgroundTasks, Depends

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.services.alerts import Mailer, get_mailer
from app.services.processing import Pipeline, process_receipt
from app.services.storage import Storage, get_storage
from app.services.textract import Extractor, get_extractor

REPROCESS = "reprocess"


def reprocess_message(receipt_id: uuid.UUID) -> str:
    return json.dumps({"type": REPROCESS, "receipt_id": str(receipt_id)})


class Dispatcher(Protocol):
    @property
    def queued(self) -> bool:
        """True when a separate worker does extraction (the API must not)."""
        ...

    async def upload_completed(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None: ...
    async def reprocess(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None: ...


class InProcessDispatcher:
    queued = False

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    async def upload_completed(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None:
        tasks.add_task(process_receipt, receipt_id, SessionLocal, self.pipeline)

    async def reprocess(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None:
        tasks.add_task(process_receipt, receipt_id, SessionLocal, self.pipeline)


class SqsDispatcher:
    queued = True

    def __init__(self, queue_url: str, region: str, client: Any | None = None) -> None:
        self.queue_url = queue_url
        self._sqs = client or boto3.client("sqs", region_name=region)

    async def upload_completed(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None:
        """Nothing to do: the S3 ObjectCreated event already queued this upload."""

    async def reprocess(self, tasks: BackgroundTasks, receipt_id: uuid.UUID) -> None:
        await asyncio.to_thread(
            self._sqs.send_message,
            QueueUrl=self.queue_url,
            MessageBody=reprocess_message(receipt_id),
        )


@lru_cache
def _sqs_dispatcher(queue_url: str, region: str) -> SqsDispatcher:
    return SqsDispatcher(queue_url, region)


def get_dispatcher(
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[Storage, Depends(get_storage)],
    extractor: Annotated[Extractor, Depends(get_extractor)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> Dispatcher:
    """FastAPI dependency. Built from the storage/extractor/mailer dependencies so tests can
    override any of them."""
    if settings.sqs_queue_url:
        return _sqs_dispatcher(settings.sqs_queue_url, settings.aws_region)
    return InProcessDispatcher(
        Pipeline(
            storage=storage,
            extractor=extractor,
            threshold=settings.low_confidence_threshold,
            mailer=mailer,
            app_base_url=settings.app_base_url,
        )
    )
