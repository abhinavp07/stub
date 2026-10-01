"""The files in demo-receipts/ extract as themselves in mock mode."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.textract import MOCK_RESPONSES_DIR
from tests.conftest import upload_receipt

DEMO_DIR = Path(__file__).parents[2] / "demo-receipts"
INDEX = json.loads((MOCK_RESPONSES_DIR / "demo_index.json").read_text())
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".pdf": "application/pdf"}
EXPECTED = {
    "grocery": ("Kroger", "25.11", False),
    "restaurant": ("Joe's Diner", "54.08", False),
    "gas_station": ("Shell Oil 57442", "48.27", False),
    "coffee": ("Starbucks #1234", "12.35", True),
    "pharmacy": ("Cvs Pharmacy", "29.19", False),
}


def test_index_matches_the_files() -> None:
    import hashlib

    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DEMO_DIR.iterdir()}
    assert {v["file"]: k for k, v in INDEX.items()} == files


@pytest.mark.parametrize("entry", INDEX.values(), ids=lambda e: e["file"])
async def test_demo_file_extracts_as_itself(client: AsyncClient, entry: dict[str, str]) -> None:
    path = DEMO_DIR / entry["file"]
    receipt = await upload_receipt(client, path.read_bytes(), CONTENT_TYPES[path.suffix], path.name)
    merchant, total, needs_review = EXPECTED[entry["sample"]]
    assert receipt["status"] == "ready"
    assert (receipt["merchant"], receipt["total"]) == (merchant, total)
    assert receipt["purchase_date"] == entry["date"]  # the date printed on the file
    assert receipt["needs_review"] is needs_review
    if needs_review:
        assert receipt["low_confidence_fields"] == ["total"]


async def test_unknown_files_come_back_empty_by_default(client: AsyncClient) -> None:
    """Outside the demo set, mock mode says nothing rather than inventing a receipt."""
    from app.main import app
    from app.services.textract import MockExtractor, get_extractor

    app.dependency_overrides[get_extractor] = lambda: MockExtractor(unknown_files="empty")
    receipt = await upload_receipt(client)
    assert receipt["status"] == "ready"
    assert receipt["merchant"] is None and receipt["total"] is None
    assert receipt["line_items"] == []
    assert receipt["needs_review"] is True
