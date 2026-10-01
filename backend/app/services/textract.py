"""Receipt extraction behind one interface: a fixture-backed mock for local dev and tests, and
Amazon Textract AnalyzeExpense for real documents."""

import asyncio
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import boto3

from app.config import Settings, get_settings
from app.services.storage import DocumentRef

MOCK_RESPONSES_DIR = Path(__file__).parent / "mock_responses"


class ExtractionError(Exception):
    """Extraction failed for a reason worth showing the user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class Extractor(Protocol):
    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        """Return a raw AnalyzeExpense response."""
        ...


class MockExtractor:
    """Stands in for Textract when TEXTRACT_MODE=mock. It never looks at the image.

    Files from demo-receipts/ are recognized by their bytes (see demo_index.json) and get
    their own data, with the date printed on them. Any other file comes back empty, so the
    receipt lands in "needs review" for the user to fill in, rather than showing invented data
    as if it had been read. Tests can set unknown_files="sample" to get a sample chosen from the
    storage key instead (stable per receipt, so reprocessing is deterministic).
    """

    def __init__(self, delay_seconds: float = 0.0, unknown_files: str = "empty") -> None:
        self.delay_seconds = delay_seconds
        self.unknown_files = unknown_files
        self._samples = sorted(
            p for p in MOCK_RESPONSES_DIR.glob("*.json") if p.stem != "demo_index"
        )
        index_path = MOCK_RESPONSES_DIR / "demo_index.json"
        self._demos: dict[str, dict[str, str]] = (
            json.loads(index_path.read_text()) if index_path.exists() else {}
        )

    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        demo = self._demos.get(hashlib.sha256(doc.data).hexdigest()) if doc.data else None
        if demo:
            data = self._load(MOCK_RESPONSES_DIR / f"{demo['sample']}.json")
            _set_date(data, demo["date"])
            return data
        if self.unknown_files == "sample":
            index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(self._samples)
            return self._load(self._samples[index])
        return {"DocumentMetadata": {"Pages": 1}, "ExpenseDocuments": []}

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(path.read_text())
        return data


def _set_date(response: dict[str, Any], iso_date: str) -> None:
    """Point the sample's receipt date at the date printed on the demo file."""
    y, m, d = iso_date.split("-")
    for f in response["ExpenseDocuments"][0]["SummaryFields"]:
        if f["Type"]["Text"] == "INVOICE_RECEIPT_DATE":
            f["ValueDetection"]["Text"] = f"{m}/{d}/{y}"
            f["ValueDetection"]["NormalizedValue"] = {
                "Value": f"{iso_date}T00:00:00",
                "ValueType": "DATE",
            }


class TextractExtractor:
    def __init__(self, region: str, client: Any | None = None) -> None:
        self._client = client or boto3.client("textract", region_name=region)

    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        if doc.s3_bucket and doc.s3_key:
            document: dict[str, Any] = {"S3Object": {"Bucket": doc.s3_bucket, "Name": doc.s3_key}}
        elif doc.data is not None:
            document = {"Bytes": doc.data}
        else:
            raise ValueError("DocumentRef has neither an S3 object nor bytes")

        errors = self._client.exceptions
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.analyze_expense, Document=document
            )
        except (errors.UnsupportedDocumentException, errors.BadDocumentException) as e:
            raise ExtractionError(
                "We couldn't read this file. Multi-page or password-protected PDFs aren't "
                "supported yet; try a photo or a single-page PDF."
            ) from e
        except errors.DocumentTooLargeException as e:
            raise ExtractionError("This file is too large for text extraction.") from e
        response.pop("ResponseMetadata", None)
        return response


def build_extractor(settings: Settings) -> Extractor:
    if settings.textract_mode == "aws":
        return TextractExtractor(settings.aws_region)
    return MockExtractor(settings.mock_textract_delay_seconds, settings.mock_unknown_files)


@lru_cache
def _default_extractor() -> Extractor:
    return build_extractor(get_settings())


def get_extractor() -> Extractor:
    """FastAPI dependency; overridden in tests."""
    return _default_extractor()
