"""File storage behind one small interface: local disk for development, S3 in production.

Both implementations hand the browser a URL to upload to directly (a presigned S3 POST, or a
signed local endpoint) so the API never has to proxy receipt files in normal operation.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import boto3
import jwt
from botocore.exceptions import ClientError

from app.config import Settings, get_settings

ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}
UPLOAD_URL_TTL_SECONDS = 15 * 60
DOWNLOAD_URL_TTL_SECONDS = 5 * 60


def receipt_key(user_id: uuid.UUID, receipt_id: uuid.UUID, content_type: str) -> str:
    return f"users/{user_id}/receipts/{receipt_id}.{ALLOWED_CONTENT_TYPES[content_type]}"


@dataclass
class PresignedUpload:
    url: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentRef:
    """What the extractor needs to read a stored document."""

    s3_bucket: str | None = None
    s3_key: str | None = None
    data: bytes | None = None


class Storage(Protocol):
    async def presign_upload(
        self, key: str, content_type: str, max_bytes: int
    ) -> PresignedUpload: ...
    async def object_size(self, key: str) -> int | None:
        """Size in bytes, or None if the object doesn't exist."""
        ...

    async def presign_download(self, key: str) -> str | None:
        """A short-lived GET URL, or None if files must be served through the API."""
        ...

    async def delete(self, key: str) -> None: ...
    async def document_ref(self, key: str) -> DocumentRef: ...


# --- Local disk -----------------------------------------------------------------------------


class LocalStorage:
    """Stores files under LOCAL_UPLOAD_DIR.

    Uploads mirror an S3 presigned POST: the browser posts a form to the returned URL with the
    returned fields, which carry a short-lived signed token (kept out of the URL so it never
    lands in access logs). Downloads go through the API's ownership-checked file endpoint.
    """

    def __init__(self, root: str | Path, secret: str) -> None:
        self.root = Path(root).resolve()
        self._secret = secret

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def _sign(self, key: str, ttl: int, **extra: Any) -> str:
        payload = {
            "typ": "local-upload",
            "key": key,
            "exp": datetime.now(UTC) + timedelta(seconds=ttl),
            **extra,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def verify_upload_token(self, token: str) -> dict[str, Any]:
        """Return the token's claims, or raise jwt.PyJWTError."""
        claims: dict[str, Any] = jwt.decode(token, self._secret, algorithms=["HS256"])
        if claims.get("typ") != "local-upload":
            raise jwt.InvalidTokenError("wrong token type")
        return claims

    async def presign_upload(self, key: str, content_type: str, max_bytes: int) -> PresignedUpload:
        token = self._sign(
            key, UPLOAD_URL_TTL_SECONDS, content_type=content_type, max_bytes=max_bytes
        )
        return PresignedUpload(url="/api/local-storage/upload", fields={"token": token})

    async def object_size(self, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    async def presign_download(self, key: str) -> str | None:
        return None

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def document_ref(self, key: str) -> DocumentRef:
        return DocumentRef(data=await asyncio.to_thread(self._path(key).read_bytes))

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def file_path(self, key: str) -> Path:
        return self._path(key)


# --- S3 -------------------------------------------------------------------------------------


class S3Storage:
    def __init__(self, bucket: str, region: str, client: Any | None = None) -> None:
        self.bucket = bucket
        self._s3 = client or boto3.client("s3", region_name=region)

    async def presign_upload(self, key: str, content_type: str, max_bytes: int) -> PresignedUpload:
        post = await asyncio.to_thread(
            self._s3.generate_presigned_post,
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=UPLOAD_URL_TTL_SECONDS,
        )
        return PresignedUpload(url=post["url"], fields=post["fields"])

    async def object_size(self, key: str) -> int | None:
        try:
            head = await asyncio.to_thread(self._s3.head_object, Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return int(head["ContentLength"])

    async def presign_download(self, key: str) -> str:
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
        )
        return url

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._s3.delete_object, Bucket=self.bucket, Key=key)

    async def document_ref(self, key: str) -> DocumentRef:
        return DocumentRef(s3_bucket=self.bucket, s3_key=key)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_mode == "s3":
        return S3Storage(settings.s3_bucket, settings.aws_region)
    return LocalStorage(settings.local_upload_dir, settings.jwt_secret)


@lru_cache
def _default_storage() -> Storage:
    return build_storage(get_settings())


def get_storage() -> Storage:
    """FastAPI dependency; overridden in tests."""
    return _default_storage()
