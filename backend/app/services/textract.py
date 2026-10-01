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
    """Returns one of the bundled sample responses, chosen deterministically from the key so a
    given receipt always gets the same data (and reprocessing is stable)."""

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds
        self._samples = sorted(MOCK_RESPONSES_DIR.glob("*.json"))

    async def analyze(self, doc: DocumentRef, key: str) -> dict[str, Any]:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(self._samples)
        data: dict[str, Any] = json.loads(self._samples[index].read_text())
        return data


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
    return MockExtractor(settings.mock_textract_delay_seconds)


@lru_cache
def _default_extractor() -> Extractor:
    return build_extractor(get_settings())


def get_extractor() -> Extractor:
    """FastAPI dependency; overridden in tests."""
    return _default_extractor()
