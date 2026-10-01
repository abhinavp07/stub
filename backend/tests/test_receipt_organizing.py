"""Phase 2: auto-categorization, learning, filters, notes/tags, deletion from S3."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from httpx import AsyncClient
from moto import mock_aws

from app.main import app
from app.services.storage import S3Storage, get_storage
from tests.conftest import PDF_BYTES, upload_receipt, use_sample


async def _category_id(client: AsyncClient, name: str) -> str:
    cats = (await client.get("/api/categories")).json()
    return next(c["id"] for c in cats if c["name"] == name)


@pytest.mark.parametrize(
    ("sample", "category"),
    [("grocery", "Groceries"), ("gas_station", "Gas"), ("restaurant", None)],
)
async def test_global_rules_auto_categorize(
    client: AsyncClient, sample: str, category: str | None
) -> None:
    use_sample(sample)
    receipt = await upload_receipt(client)
    expected = await _category_id(client, category) if category else None
    assert receipt["category_id"] == expected


async def test_changing_category_teaches_a_user_rule(client: AsyncClient) -> None:
    use_sample("restaurant")  # Joe's Diner: no global rule
    first = await upload_receipt(client)
    assert first["category_id"] is None

    dining = await _category_id(client, "Dining")
    await client.patch(f"/api/receipts/{first['id']}", json={"category_id": dining})

    second = await upload_receipt(client)
    assert second["category_id"] == dining


async def test_user_rules_override_global_rules(client: AsyncClient) -> None:
    use_sample("gas_station")  # Shell -> Gas globally
    first = await upload_receipt(client)
    travel = await _category_id(client, "Travel")
    await client.patch(f"/api/receipts/{first['id']}", json={"category_id": travel})
    second = await upload_receipt(client)
    assert second["category_id"] == travel


async def test_correcting_merchant_recategorizes_unless_user_picked(client: AsyncClient) -> None:
    use_sample("restaurant")
    receipt = await upload_receipt(client)
    resp = await client.patch(f"/api/receipts/{receipt['id']}", json={"merchant": "Starbucks #12"})
    assert resp.json()["category_id"] == await _category_id(client, "Dining")

    other = await _category_id(client, "Other")
    await client.patch(f"/api/receipts/{receipt['id']}", json={"category_id": other})
    resp = await client.patch(f"/api/receipts/{receipt['id']}", json={"merchant": "Kroger"})
    assert resp.json()["category_id"] == other


async def test_reprocess_keeps_user_category_notes_and_tags(client: AsyncClient) -> None:
    use_sample("grocery")
    receipt = await upload_receipt(client)
    other = await _category_id(client, "Other")
    await client.patch(
        f"/api/receipts/{receipt['id']}",
        json={"category_id": other, "notes": "split with Sam", "tags": ["shared"]},
    )
    await client.post(f"/api/receipts/{receipt['id']}/reprocess")
    fresh = (await client.get(f"/api/receipts/{receipt['id']}")).json()
    assert fresh["status"] == "ready"
    assert fresh["category_id"] == other
    assert fresh["notes"] == "split with Sam"
    assert fresh["tags"] == ["shared"]
    assert "category_id" in fresh["user_edited_fields"]


async def test_list_includes_thumbnails_for_images_only(client: AsyncClient) -> None:
    img = await upload_receipt(client)
    pdf = await upload_receipt(client, PDF_BYTES, "application/pdf", "r.pdf")
    items = {r["id"]: r for r in (await client.get("/api/receipts")).json()["items"]}
    assert items[img["id"]]["thumbnail_url"] == f"/api/receipts/{img['id']}/file"
    assert items[pdf["id"]]["thumbnail_url"] is None


# --- Filters --------------------------------------------------------------------------------


@pytest.fixture
async def dataset(client: AsyncClient) -> dict[str, str]:
    """Five receipts with hand-set values, keyed by a short name."""
    groceries = await _category_id(client, "Groceries")
    dining = await _category_id(client, "Dining")
    rows: dict[str, dict[str, Any]] = {
        "kroger_jan": dict(merchant="Kroger", purchase_date="2024-01-10", total="50.00",
                           category_id=groceries, tags=["food"], needs_review=False),
        "kroger_mar": dict(merchant="KROGER #42", purchase_date="2024-03-05", total="120.00",
                           category_id=groceries, tags=["food", "party"], needs_review=True),
        "joes_feb": dict(merchant="Joe's Diner", purchase_date="2024-02-14", total="35.50",
                         category_id=dining, tags=["date night"], needs_review=False),
        "cafe_mar": dict(merchant="Corner Cafe_1", purchase_date="2024-03-20", total="8.25",
                         category_id=None, tags=[], needs_review=True),
        "shell_apr": dict(merchant="Shell", purchase_date="2024-04-01", total="61.00",
                          category_id=None, tags=["car"], needs_review=False),
    }  # fmt: skip
    ids = {}
    for name, values in rows.items():
        r = await upload_receipt(client)
        resp = await client.patch(f"/api/receipts/{r['id']}", json=values)
        assert resp.status_code == 200, resp.text
        ids[name] = r["id"]
    return ids


async def _ids(client: AsyncClient, ids: dict[str, str], **params: Any) -> set[str]:
    resp = await client.get("/api/receipts", params={"limit": 100, **params})
    assert resp.status_code == 200, resp.text
    by_id = {v: k for k, v in ids.items()}
    return {by_id[r["id"]] for r in resp.json()["items"]}


async def test_search_is_case_insensitive_and_partial(
    client: AsyncClient, dataset: dict[str, str]
) -> None:
    assert await _ids(client, dataset, q="kro") == {"kroger_jan", "kroger_mar"}
    assert await _ids(client, dataset, q="DINER") == {"joes_feb"}
    assert await _ids(client, dataset, q="joe's") == {"joes_feb"}
    # LIKE wildcards in the search are literal.
    assert await _ids(client, dataset, q="cafe_") == {"cafe_mar"}
    assert await _ids(client, dataset, q="%") == set()


async def test_each_filter(client: AsyncClient, dataset: dict[str, str]) -> None:
    groceries = await _category_id(client, "Groceries")
    assert await _ids(client, dataset, category_id=groceries) == {"kroger_jan", "kroger_mar"}
    assert await _ids(client, dataset, category_id="none") == {"cafe_mar", "shell_apr"}
    assert await _ids(client, dataset, date_from="2024-03-01") == {
        "kroger_mar", "cafe_mar", "shell_apr",
    }  # fmt: skip
    assert await _ids(client, dataset, date_to="2024-02-14") == {"kroger_jan", "joes_feb"}
    assert await _ids(client, dataset, min_total="61") == {"kroger_mar", "shell_apr"}
    assert await _ids(client, dataset, max_total="35.50") == {"joes_feb", "cafe_mar"}
    assert await _ids(client, dataset, needs_review="true") == {"kroger_mar", "cafe_mar"}
    assert await _ids(client, dataset, needs_review="false") == {
        "kroger_jan", "joes_feb", "shell_apr",
    }  # fmt: skip
    assert await _ids(client, dataset, tag="food") == {"kroger_jan", "kroger_mar"}
    assert await _ids(client, dataset, tag="date night") == {"joes_feb"}
    assert await _ids(client, dataset, status="ready") == set(dataset)
    assert await _ids(client, dataset, status="failed") == set()


async def test_filters_combine(client: AsyncClient, dataset: dict[str, str]) -> None:
    groceries = await _category_id(client, "Groceries")
    assert await _ids(
        client, dataset, q="kroger", category_id=groceries, date_from="2024-02-01", tag="party"
    ) == {"kroger_mar"}
    assert await _ids(
        client, dataset, min_total="10", max_total="100", needs_review="false", date_to="2024-03-31"
    ) == {"kroger_jan", "joes_feb"}
    assert await _ids(client, dataset, q="kroger", needs_review="false", tag="party") == set()


async def test_filters_with_pagination_and_total_sort(
    client: AsyncClient, dataset: dict[str, str]
) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 1, "sort": "total", "min_total": "30"}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/api/receipts", params=params)).json()
        seen += [r["total"] for r in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["120.00", "61.00", "50.00", "35.50"]


async def test_filter_validation(client: AsyncClient) -> None:
    for params in ({"category_id": "nope"}, {"date_from": "yesterday"}, {"status": "weird"}):
        assert (await client.get("/api/receipts", params=params)).status_code == 422


async def test_tags_are_validated(client: AsyncClient) -> None:
    receipt = await upload_receipt(client)
    resp = await client.patch(f"/api/receipts/{receipt['id']}", json={"tags": ["x" * 41]})
    assert resp.status_code == 422


# --- Deleting removes the S3 object ---------------------------------------------------------

BUCKET = "test-receipts"


@pytest.fixture
def s3_storage() -> Iterator[S3Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        storage = S3Storage(BUCKET, "us-east-1", client=client)
        app.dependency_overrides[get_storage] = lambda: storage
        yield storage


async def test_delete_removes_row_and_s3_object(client: AsyncClient, s3_storage: S3Storage) -> None:
    resp = await client.post(
        "/api/receipts/upload-url",
        json={"filename": "r.jpg", "content_type": "image/jpeg", "size_bytes": 4},
    )
    body = resp.json()
    assert body["upload_url"].startswith("https://") and "policy" in body["fields"]
    key = body["fields"]["key"]
    # Stand in for the browser's direct-to-S3 POST.
    s3_storage._s3.put_object(Bucket=BUCKET, Key=key, Body=b"\xff\xd8\xff\xe0")

    assert (await client.post(f"/api/receipts/{body['receipt_id']}/complete")).status_code == 200
    detail = (await client.get(f"/api/receipts/{body['receipt_id']}")).json()
    assert detail["status"] == "ready"
    assert "Signature" in detail["image_url"]  # presigned S3 GET
    assert await s3_storage.object_size(key) == 4

    assert (await client.delete(f"/api/receipts/{body['receipt_id']}")).status_code == 204
    assert await s3_storage.object_size(key) is None
    assert (await client.get(f"/api/receipts/{body['receipt_id']}")).status_code == 404
