import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.main import app
from app.services.storage import DocumentRef
from app.services.textract import MOCK_RESPONSES_DIR, ExtractionError, get_extractor
from tests.conftest import (
    JPEG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    ClientFactory,
    upload_receipt,
)


async def test_upload_flow_extracts_receipt(client: AsyncClient) -> None:
    receipt = await upload_receipt(client)
    assert receipt["status"] == "ready"
    assert receipt["error_message"] is None
    assert receipt["merchant"]
    assert receipt["purchase_date"]
    assert isinstance(receipt["total"], str)  # money is sent as a string
    assert len(receipt["line_items"]) >= 2
    assert receipt["field_confidence"]["total"] > 90
    assert receipt["needs_review"] is False
    assert receipt["image_url"] == f"/api/receipts/{receipt['id']}/file"

    file = await client.get(receipt["image_url"])
    assert file.status_code == 200
    assert file.content == JPEG_BYTES
    assert file.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    ("data", "content_type", "filename"),
    [(PNG_BYTES, "image/png", "r.png"), (PDF_BYTES, "application/pdf", "r.pdf")],
)
async def test_png_and_pdf_uploads(
    client: AsyncClient, data: bytes, content_type: str, filename: str
) -> None:
    receipt = await upload_receipt(client, data, content_type, filename)
    assert receipt["status"] == "ready"
    assert receipt["content_type"] == content_type


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"filename": "x.gif", "content_type": "image/gif", "size_bytes": 100},
            "Only JPG, PNG and PDF files are supported",
        ),
        (
            {"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10 * 1024 * 1024 + 1},
            "Files must be 10 MB or smaller",
        ),
    ],
)
async def test_upload_url_rejects_bad_type_and_size(
    client: AsyncClient, payload: dict[str, Any], message: str
) -> None:
    resp = await client.post("/api/receipts/upload-url", json=payload)
    assert resp.status_code == 400
    assert resp.json() == {"detail": message}


async def test_exactly_ten_megabytes_is_allowed(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10 * 1024 * 1024},
    )
    assert resp.status_code == 201


async def test_local_upload_enforces_size_and_type(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10},
    )
    body = resp.json()
    too_big = b"\x00" * (10 * 1024 * 1024 + 1)
    r = await client.post(
        body["upload_url"], data=body["fields"], files={"file": ("x.jpg", too_big, "image/jpeg")}
    )
    assert r.status_code == 413
    r = await client.post(
        body["upload_url"], data=body["fields"], files={"file": ("x.png", PNG_BYTES, "image/png")}
    )
    assert r.status_code == 400
    r = await client.post(
        body["upload_url"],
        data={"token": "forged"},
        files={"file": ("x.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert r.status_code == 403


async def test_complete_without_upload_fails(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10},
    )
    rid = resp.json()["receipt_id"]
    done = await client.post(f"/api/receipts/{rid}/complete")
    assert done.status_code == 400
    assert done.json() == {"detail": "Upload not found. Try uploading again."}


async def test_complete_is_idempotent(client: AsyncClient) -> None:
    """A retried /complete (or one arriving after the S3 event started processing in queue
    mode) reports the current state and doesn't process again."""
    receipt = await upload_receipt(client)
    await client.patch(f"/api/receipts/{receipt['id']}", json={"merchant": "Kept"})
    again = await client.post(f"/api/receipts/{receipt['id']}/complete")
    assert again.status_code == 200
    assert again.json()["status"] == "ready"
    assert again.json()["merchant"] == "Kept"


class _FailingExtractor:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (ExtractionError("We couldn't read this file."), "We couldn't read this file."),
        (
            RuntimeError("boom: internal detail"),
            "Something went wrong while reading this receipt. Try reprocessing it.",
        ),
    ],
)
async def test_extraction_failure_marks_receipt_failed(
    client: AsyncClient, exc: Exception, message: str
) -> None:
    app.dependency_overrides[get_extractor] = lambda: _FailingExtractor(exc)
    receipt = await upload_receipt(client)
    assert receipt["status"] == "failed"
    assert receipt["error_message"] == message


async def test_list_paginates_newest_purchase_first(client: AsyncClient) -> None:
    ids = []
    for _ in range(5):
        ids.append((await upload_receipt(client))["id"])
    # One receipt left un-uploaded never shows in the list.
    await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10},
    )

    seen: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/api/receipts", params=params)).json()
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert sorted(r["id"] for r in seen) == sorted(ids)
    dates = [r["purchase_date"] for r in seen]
    assert dates == sorted(dates, reverse=True)


async def test_list_sort_by_total_and_bad_cursor(client: AsyncClient) -> None:
    for _ in range(3):
        await upload_receipt(client)
    items = (await client.get("/api/receipts", params={"sort": "total"})).json()["items"]
    totals = [float(r["total"]) for r in items]
    assert totals == sorted(totals, reverse=True)
    bad = await client.get("/api/receipts", params={"cursor": "garbage"})
    assert bad.status_code == 400


async def test_edits_persist_and_are_tracked(client: AsyncClient) -> None:
    receipt = await upload_receipt(client)
    rid = receipt["id"]
    resp = await client.patch(
        f"/api/receipts/{rid}",
        json={
            "merchant": "  Corrected Name ",
            "total": "99.99",
            "purchase_date": "2024-12-25",
            "notes": "client lunch",
            "tags": ["work", " work ", "", "tax"],
            # Sending the current value is not an edit.
            "subtotal": receipt["subtotal"],
        },
    )
    assert resp.status_code == 200, resp.text
    fresh = (await client.get(f"/api/receipts/{rid}")).json()
    assert fresh["merchant"] == "Corrected Name"
    assert fresh["total"] == "99.99"
    assert fresh["purchase_date"] == "2024-12-25"
    assert fresh["notes"] == "client lunch"
    assert fresh["tags"] == ["work", "tax"]
    assert set(fresh["user_edited_fields"]) == {"merchant", "total", "purchase_date"}


async def test_patch_confirm_clears_needs_review(client: AsyncClient) -> None:
    rid = (await upload_receipt(client))["id"]
    await client.patch(f"/api/receipts/{rid}", json={"needs_review": True})
    resp = await client.patch(f"/api/receipts/{rid}", json={"needs_review": False})
    assert resp.json()["needs_review"] is False


async def test_patch_validation(client: AsyncClient) -> None:
    rid = (await upload_receipt(client))["id"]
    assert (await client.patch(f"/api/receipts/{rid}", json={"total": "1.234"})).status_code == 422
    assert (await client.patch(f"/api/receipts/{rid}", json={"bogus": 1})).status_code == 422
    resp = await client.patch(f"/api/receipts/{rid}", json={"category_id": str(uuid.uuid4())})
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Category not found"}


async def test_replace_line_items(client: AsyncClient) -> None:
    rid = (await upload_receipt(client))["id"]
    resp = await client.put(
        f"/api/receipts/{rid}/line-items",
        json=[
            {"description": "Coffee", "quantity": "2", "unit_price": "3.50", "amount": "7.00"},
            {"description": "Bagel", "amount": "2.25"},
        ],
    )
    assert resp.status_code == 200, resp.text
    fresh = (await client.get(f"/api/receipts/{rid}")).json()
    assert [(li["description"], li["amount"]) for li in fresh["line_items"]] == [
        ("Coffee", "7.00"),
        ("Bagel", "2.25"),
    ]
    assert [li["position"] for li in fresh["line_items"]] == [0, 1]
    assert "line_items" in fresh["user_edited_fields"]


async def test_reprocess_keeps_user_edits(client: AsyncClient) -> None:
    receipt = await upload_receipt(client)
    rid = receipt["id"]
    await client.patch(f"/api/receipts/{rid}", json={"merchant": "Mine", "total": "1.00"})
    await client.put(f"/api/receipts/{rid}/line-items", json=[{"description": "Only item"}])

    resp = await client.post(f"/api/receipts/{rid}/reprocess")
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
    fresh = (await client.get(f"/api/receipts/{rid}")).json()
    assert fresh["status"] == "ready"
    assert fresh["merchant"] == "Mine"
    assert fresh["total"] == "1.00"
    assert [li["description"] for li in fresh["line_items"]] == ["Only item"]
    assert fresh["purchase_date"] == receipt["purchase_date"]  # unedited field re-extracted


async def test_reprocess_requires_finished_receipt(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10},
    )
    rid = resp.json()["receipt_id"]
    assert (await client.post(f"/api/receipts/{rid}/reprocess")).status_code == 409


async def test_delete_removes_row_and_file(client: AsyncClient) -> None:
    receipt = await upload_receipt(client)
    rid = receipt["id"]
    stored = list(Path(os.environ["LOCAL_UPLOAD_DIR"]).rglob(f"{rid}.*"))
    assert len(stored) == 1

    resp = await client.delete(f"/api/receipts/{rid}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/receipts/{rid}")).status_code == 404
    assert not stored[0].exists()


async def test_receipt_routes_require_auth(make_client: ClientFactory) -> None:
    anon = await make_client()
    assert (await anon.get("/api/receipts")).status_code == 401
    assert (
        await anon.post(
            "/api/receipts/upload-url",
            json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 1},
        )
    ).status_code == 401


# --- Ownership: user A gets 404 for user B's receipt on every receipt endpoint ---------------

OWNERSHIP_CASES: list[tuple[str, str, Any]] = [
    ("GET", "/api/receipts/{id}", None),
    ("GET", "/api/receipts/{id}/file", None),
    ("PATCH", "/api/receipts/{id}", {"merchant": "hijack"}),
    ("PUT", "/api/receipts/{id}/line-items", [{"description": "hijack"}]),
    ("POST", "/api/receipts/{id}/reprocess", None),
    ("POST", "/api/receipts/{id}/complete", None),
    ("DELETE", "/api/receipts/{id}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), OWNERSHIP_CASES)
async def test_other_users_receipt_is_404(
    make_client: ClientFactory, method: str, path: str, body: Any
) -> None:
    owner = await make_client("owner@example.com")
    intruder = await make_client("intruder@example.com")
    receipt = await upload_receipt(owner)
    url = path.format(id=receipt["id"])

    resp = await intruder.request(method, url, json=body)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Receipt not found"}

    # Indistinguishable from a receipt that doesn't exist at all.
    missing = await intruder.request(method, path.format(id=uuid.uuid4()), json=body)
    assert missing.status_code == 404
    assert missing.json() == resp.json()

    # And the owner's receipt is untouched.
    after = (await owner.get(f"/api/receipts/{receipt['id']}")).json()
    assert after["merchant"] == receipt["merchant"]
    assert after["line_items"] == receipt["line_items"]


async def test_complete_on_pending_receipt_of_other_user_is_404(
    make_client: ClientFactory,
) -> None:
    owner = await make_client("owner@example.com")
    intruder = await make_client("intruder@example.com")
    resp = await owner.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": 10},
    )
    rid = resp.json()["receipt_id"]
    assert (await intruder.post(f"/api/receipts/{rid}/complete")).status_code == 404


async def test_list_only_shows_own_receipts(make_client: ClientFactory) -> None:
    a = await make_client("a@example.com")
    b = await make_client("b@example.com")
    await upload_receipt(a)
    await upload_receipt(b)
    await upload_receipt(b)
    assert len((await a.get("/api/receipts")).json()["items"]) == 1
    assert len((await b.get("/api/receipts")).json()["items"]) == 2


async def test_low_confidence_fields_reported_until_edited(client: AsyncClient) -> None:
    class _LowConfidence:
        async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
            data = json.loads((MOCK_RESPONSES_DIR / "grocery.json").read_text())
            for f in data["ExpenseDocuments"][0]["SummaryFields"]:
                if f["Type"]["Text"] in ("TOTAL", "TAX"):
                    f["ValueDetection"]["Confidence"] = 55.0
            return data

    app.dependency_overrides[get_extractor] = _LowConfidence
    receipt = await upload_receipt(client)
    assert receipt["needs_review"] is True
    assert sorted(receipt["low_confidence_fields"]) == ["tax", "total"]

    resp = await client.patch(f"/api/receipts/{receipt['id']}", json={"total": "1.00"})
    assert resp.json()["low_confidence_fields"] == ["tax"]


async def test_edits_made_during_processing_are_not_overwritten(client: AsyncClient) -> None:
    """The user edits the receipt while extraction is still running; saving the extraction
    results must respect those edits rather than clobber them with a stale copy."""
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import Receipt

    class _UserEditsMidway:
        async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
            rid = uuid.UUID(Path(key).stem)
            async with SessionLocal() as s:
                await s.execute(
                    update(Receipt)
                    .where(Receipt.id == rid)
                    .values(merchant="Typed by user", user_edited_fields=["merchant"])
                )
                await s.commit()
            return json.loads((MOCK_RESPONSES_DIR / "grocery.json").read_text())

    app.dependency_overrides[get_extractor] = _UserEditsMidway
    receipt = await upload_receipt(client)
    assert receipt["status"] == "ready"
    assert receipt["merchant"] == "Typed by user"
    assert receipt["total"] == "25.11"  # unedited fields still extracted
    assert receipt["user_edited_fields"] == ["merchant"]


async def test_receipt_deleted_during_processing(client: AsyncClient) -> None:
    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models import Receipt

    class _DeletedMidway:
        async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
            async with SessionLocal() as s:
                await s.execute(delete(Receipt).where(Receipt.id == uuid.UUID(Path(key).stem)))
                await s.commit()
            return json.loads((MOCK_RESPONSES_DIR / "grocery.json").read_text())

    app.dependency_overrides[get_extractor] = _DeletedMidway
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "x.jpg", "content_type": "image/jpeg", "size_bytes": len(JPEG_BYTES)},
    )
    body = resp.json()
    await client.post(
        body["upload_url"], data=body["fields"], files={"file": ("x.jpg", JPEG_BYTES, "image/jpeg")}
    )
    # Processing finds the row gone and quietly stops; nothing is resurrected.
    assert (await client.post(f"/api/receipts/{body['receipt_id']}/complete")).status_code == 200
    assert (await client.get(f"/api/receipts/{body['receipt_id']}")).status_code == 404
