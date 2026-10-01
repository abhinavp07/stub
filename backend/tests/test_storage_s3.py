import base64
import json
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from app.services.storage import S3Storage

BUCKET = "test-receipts"
KEY = "users/u1/receipts/r1.jpg"


@pytest.fixture
def s3() -> Iterator[S3Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield S3Storage(BUCKET, "us-east-1", client=client)


async def test_presigned_post_restricts_type_and_size(s3: S3Storage) -> None:
    upload = await s3.presign_upload(KEY, "image/jpeg", 10 * 1024 * 1024)
    assert BUCKET in upload.url
    assert upload.fields["key"] == KEY
    assert upload.fields["Content-Type"] == "image/jpeg"
    assert "policy" in upload.fields

    policy = json.loads(base64.b64decode(upload.fields["policy"]))
    assert ["content-length-range", 1, 10 * 1024 * 1024] in policy["conditions"]
    assert {"Content-Type": "image/jpeg"} in policy["conditions"]


async def test_object_size_delete_and_download(s3: S3Storage) -> None:
    assert await s3.object_size(KEY) is None
    s3._s3.put_object(Bucket=BUCKET, Key=KEY, Body=b"12345")
    assert await s3.object_size(KEY) == 5

    url = await s3.presign_download(KEY)
    assert url is not None and KEY in url and "Signature" in url

    ref = await s3.document_ref(KEY)
    assert (ref.s3_bucket, ref.s3_key, ref.data) == (BUCKET, KEY, None)

    await s3.delete(KEY)
    assert await s3.object_size(KEY) is None
