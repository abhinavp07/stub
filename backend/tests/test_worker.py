"""The SQS pipeline: S3 events and reprocess messages, idempotency, locking, and the DLQ."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws
from sqlalchemy import text, update

from app.config import get_settings
from app.db import SessionLocal, engine
from app.main import app
from app.models import Receipt, ReceiptStatus
from app.services.dispatch import SqsDispatcher, get_dispatcher
from app.services.processing import Pipeline
from app.services.storage import DocumentRef, S3Storage, get_storage
from app.services.textract import MOCK_RESPONSES_DIR
from app.worker import BadMessage, Worker, handle, parse_message, receipt_lock

BUCKET = "test-receipts"
REGION = "us-east-1"


class CountingExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        self.calls += 1
        return json.loads((MOCK_RESPONSES_DIR / "grocery.json").read_text())


@dataclass
class Env:
    s3: Any
    sqs: Any
    queue_url: str
    dlq_url: str
    storage: S3Storage
    extractor: CountingExtractor
    worker: Worker


def s3_event(key: str, event: str = "ObjectCreated:Post") -> str:
    return json.dumps(
        {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": event,
                    "s3": {"bucket": {"name": BUCKET}, "object": {"key": key, "size": 4}},
                }
            ]
        }
    )


@pytest.fixture
def env() -> Iterator[Env]:
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        sqs = boto3.client("sqs", region_name=REGION)
        dlq_url = sqs.create_queue(QueueName="receipts-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        queue_url = sqs.create_queue(
            QueueName="receipts",
            Attributes={
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"}
                ),
                "VisibilityTimeout": "0",
            },
        )["QueueUrl"]
        storage = S3Storage(BUCKET, REGION, client=s3)
        extractor = CountingExtractor()
        settings = get_settings().model_copy(
            update={"sqs_queue_url": queue_url, "storage_mode": "s3"}
        )
        pipeline = Pipeline(storage=storage, extractor=extractor, threshold=80)
        worker = Worker(settings, SessionLocal, engine, pipeline, sqs=sqs)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_storage] = lambda: storage
        app.dependency_overrides[get_dispatcher] = lambda: SqsDispatcher(
            queue_url, REGION, client=sqs
        )
        yield Env(s3, sqs, queue_url, dlq_url, storage, extractor, worker)


async def _start_upload(client: AsyncClient, env: Env) -> tuple[str, str]:
    """Get an upload URL and put the object, as the browser would. Returns (id, key)."""
    body = (
        await client.post(
            "/api/receipts/upload-url",
            json={"filename": "r.jpg", "content_type": "image/jpeg", "size_bytes": 4},
        )
    ).json()
    key = body["fields"]["key"]
    env.s3.put_object(Bucket=BUCKET, Key=key, Body=b"\xff\xd8\xff\xe0")
    return body["receipt_id"], key


def _queue_depth(env: Env, url: str) -> int:
    attrs = env.sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]) + int(
        attrs["ApproximateNumberOfMessagesNotVisible"]
    )


# --- Message parsing -----------------------------------------------------------------------


def test_parse_s3_event_with_url_encoded_key() -> None:
    uid, rid = uuid.uuid4(), uuid.uuid4()
    key = f"users/{uid}/receipts/{rid}.jpg"
    assert parse_message(s3_event(key.replace("/", "%2F"))) == [("upload", rid, uid)]


def test_parse_ignores_test_events_deletes_and_foreign_keys() -> None:
    assert parse_message(json.dumps({"Event": "s3:TestEvent"})) == []
    uid, rid = uuid.uuid4(), uuid.uuid4()
    assert parse_message(s3_event(f"users/{uid}/receipts/{rid}.jpg", "ObjectRemoved:Delete")) == []
    assert parse_message(s3_event("some/other/file.txt")) == []


def test_parse_reprocess_and_garbage() -> None:
    rid = uuid.uuid4()
    msg = json.dumps({"type": "reprocess", "receipt_id": str(rid)})
    assert parse_message(msg) == [("reprocess", rid, None)]
    for bad in ("not json", "[]", json.dumps({"hello": 1}), json.dumps({"type": "reprocess"})):
        with pytest.raises(BadMessage):
            parse_message(bad)


# --- The pipeline end to end ----------------------------------------------------------------


async def test_queue_mode_api_does_not_extract(client: AsyncClient, env: Env) -> None:
    rid, _ = await _start_upload(client, env)
    resp = await client.post(f"/api/receipts/{rid}/complete")
    assert resp.json()["status"] == "processing"
    assert env.extractor.calls == 0
    # The API didn't enqueue the upload itself: the S3 event does that.
    assert _queue_depth(env, env.queue_url) == 0


async def test_s3_event_processes_upload(client: AsyncClient, env: Env) -> None:
    rid, key = await _start_upload(client, env)
    await client.post(f"/api/receipts/{rid}/complete")
    env.sqs.send_message(QueueUrl=env.queue_url, MessageBody=s3_event(key))

    assert await env.worker.poll_once(wait_seconds=0) == 1
    detail = (await client.get(f"/api/receipts/{rid}")).json()
    assert detail["status"] == "ready"
    assert detail["merchant"] == "Kroger"
    assert env.extractor.calls == 1
    assert _queue_depth(env, env.queue_url) == 0  # deleted after success


async def test_s3_event_before_complete(client: AsyncClient, env: Env) -> None:
    """S3 can notify before the browser calls /complete; the worker starts anyway and the
    later /complete just reports the state."""
    rid, key = await _start_upload(client, env)
    env.sqs.send_message(QueueUrl=env.queue_url, MessageBody=s3_event(key))
    await env.worker.poll_once(wait_seconds=0)

    resp = await client.post(f"/api/receipts/{rid}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
    assert env.extractor.calls == 1


async def test_duplicate_delivery_is_skipped(client: AsyncClient, env: Env) -> None:
    rid, key = await _start_upload(client, env)
    for _ in range(3):
        env.sqs.send_message(QueueUrl=env.queue_url, MessageBody=s3_event(key))
    for _ in range(3):
        await env.worker.poll_once(wait_seconds=0)
    assert env.extractor.calls == 1  # Textract billed once
    assert _queue_depth(env, env.queue_url) == 0


async def test_reprocess_goes_through_the_queue(client: AsyncClient, env: Env) -> None:
    rid, key = await _start_upload(client, env)
    env.sqs.send_message(QueueUrl=env.queue_url, MessageBody=s3_event(key))
    await env.worker.poll_once(wait_seconds=0)
    await client.patch(f"/api/receipts/{rid}", json={"merchant": "Mine"})

    resp = await client.post(f"/api/receipts/{rid}/reprocess")
    assert resp.json()["status"] == "processing"
    assert _queue_depth(env, env.queue_url) == 1
    await env.worker.poll_once(wait_seconds=0)

    detail = (await client.get(f"/api/receipts/{rid}")).json()
    assert detail["status"] == "ready"
    assert detail["merchant"] == "Mine"  # user edit survives
    assert env.extractor.calls == 2


async def test_failed_receipts_wait_for_explicit_reprocess(client: AsyncClient, env: Env) -> None:
    rid, key = await _start_upload(client, env)
    async with SessionLocal() as s:
        await s.execute(
            update(Receipt).where(Receipt.id == uuid.UUID(rid)).values(status=ReceiptStatus.failed)
        )
        await s.commit()
    outcome = await handle(
        "upload", uuid.UUID(rid), None, SessionLocal, engine, env.worker.pipeline
    )
    assert outcome == "failed-skip"
    assert env.extractor.calls == 0


async def test_missing_and_mismatched_receipts(client: AsyncClient, env: Env) -> None:
    pipeline = env.worker.pipeline
    assert await handle("upload", uuid.uuid4(), None, SessionLocal, engine, pipeline) == "missing"
    rid, _ = await _start_upload(client, env)
    stranger = uuid.uuid4()
    assert (
        await handle("upload", uuid.UUID(rid), stranger, SessionLocal, engine, pipeline)
        == "mismatch"
    )
    assert env.extractor.calls == 0


async def test_locked_receipt_is_left_to_the_other_worker(client: AsyncClient, env: Env) -> None:
    rid, _ = await _start_upload(client, env)
    async with receipt_lock(engine, uuid.UUID(rid)) as held:
        assert held
        outcome = await handle(
            "upload", uuid.UUID(rid), None, SessionLocal, engine, env.worker.pipeline
        )
    assert outcome == "locked"
    assert env.extractor.calls == 0


async def test_bad_messages_go_to_the_dlq(env: Env) -> None:
    env.sqs.send_message(QueueUrl=env.queue_url, MessageBody="definitely not json")
    # Not deleted on failure; after maxReceiveCount (2) receives SQS moves it to the DLQ.
    for _ in range(3):
        await env.worker.poll_once(wait_seconds=0)
    assert _queue_depth(env, env.queue_url) == 0
    dead = env.sqs.receive_message(QueueUrl=env.dlq_url, MaxNumberOfMessages=1)["Messages"]
    assert dead[0]["Body"] == "definitely not json"


async def test_worker_survives_database_errors(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Infrastructure errors leave the message for a retry instead of crashing the worker."""
    import app.worker as worker_module

    async def boom(*args: object, **kwargs: object) -> str:
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(worker_module, "handle", boom)
    rid = uuid.uuid4()
    env.sqs.send_message(
        QueueUrl=env.queue_url,
        MessageBody=json.dumps({"type": "reprocess", "receipt_id": str(rid)}),
    )
    message = env.sqs.receive_message(QueueUrl=env.queue_url)["Messages"][0]
    assert await env.worker.handle_message(message) is False
    assert _queue_depth(env, env.queue_url) == 1


async def test_receipt_lock_is_exclusive() -> None:
    rid = uuid.uuid4()
    async with receipt_lock(engine, rid) as first, receipt_lock(engine, rid) as second:
        assert first and not second
    async with receipt_lock(engine, rid) as again:
        assert again
    # Every lock was released.
    async with engine.connect() as conn:
        held = await conn.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted")
        )
    assert held == 0
