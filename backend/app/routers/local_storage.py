"""Stand-in for S3 presigned POST uploads when STORAGE_MODE=local."""

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.services.storage import LocalStorage, Storage, get_storage

router = APIRouter(prefix="/local-storage", tags=["local-storage"])

_CHUNK = 1024 * 1024


def _local(storage: Annotated[Storage, Depends(get_storage)]) -> LocalStorage:
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return storage


@router.post("/upload", status_code=status.HTTP_204_NO_CONTENT)
async def upload(
    token: Annotated[str, Form()],
    file: UploadFile,
    storage: Annotated[LocalStorage, Depends(_local)],
) -> None:
    try:
        claims = storage.verify_upload_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Upload link is invalid or expired"
        ) from None
    if file.content_type != claims["content_type"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File type does not match the upload")

    max_bytes: int = claims["max_bytes"]
    data = bytearray()
    while chunk := await file.read(_CHUNK):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File is too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    storage.write(claims["key"], bytes(data))
