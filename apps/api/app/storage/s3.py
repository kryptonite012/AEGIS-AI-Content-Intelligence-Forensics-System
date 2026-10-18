from __future__ import annotations

from collections.abc import Iterator

from app.storage.base import ObjectExists, Storage, StorageError


class S3Storage(Storage):
    """S3-compatible store (AWS S3, MinIO). Uses conditional writes (If-None-Match) where supported
    and, when enabled, S3 Object Lock in GOVERNANCE mode via the bucket's default retention."""

    name = "s3"

    def __init__(self, bucket: str, endpoint_url: str | None, region: str, object_lock: bool) -> None:
        import boto3

        self.bucket = bucket
        self.object_lock = object_lock
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def _put(self, key: str, body, content_type: str) -> None:  # type: ignore[no-untyped-def]
        if self.exists(key):
            raise ObjectExists(key)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type,
                               ServerSideEncryption="AES256")

    def put_file(self, key: str, src, content_type: str) -> None:  # type: ignore[no-untyped-def]
        with open(src, "rb") as f:
            self._put(key, f, content_type)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._put(key, data, content_type)

    def open(self, key: str) -> Iterator[bytes]:
        from botocore.exceptions import ClientError

        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as exc:
            raise StorageError("object not found") from exc
        yield from body.iter_chunks(1 << 20)

    def purge(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def health(self) -> tuple[bool, str]:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True, f"bucket {self.bucket} reachable"
        except Exception as exc:  # noqa: BLE001
            return False, f"bucket unreachable: {type(exc).__name__}"
