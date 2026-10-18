"""Evidence object storage. Objects are content-addressed and write-once: an existing key is never
overwritten. Deletion is only possible through the retention purge path, which is audited."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


class StorageError(RuntimeError):
    pass


class ObjectExists(StorageError):
    pass


class Storage(ABC):
    name: str

    @abstractmethod
    def put_file(self, key: str, src: Path, content_type: str) -> None: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def open(self, key: str) -> Iterator[bytes]: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def purge(self, key: str) -> None: ...

    @abstractmethod
    def health(self) -> tuple[bool, str]: ...

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """A local filesystem path to read the object (downloads to a temp file for remote stores)."""
        import tempfile

        with tempfile.NamedTemporaryFile(prefix="aegis-obj-") as tmp:
            for chunk in self.open(key):
                tmp.write(chunk)
            tmp.flush()
            yield Path(tmp.name)

    def sha256(self, key: str) -> tuple[str, int]:
        h = hashlib.sha256()
        n = 0
        for chunk in self.open(key):
            h.update(chunk)
            n += len(chunk)
        return h.hexdigest(), n


def evidence_key(org_id: str, sha256: str, kind: str = "original") -> str:
    return f"orgs/{org_id}/{kind}/{sha256[:2]}/{sha256}"


@lru_cache
def get_storage() -> Storage:
    from app.core.config import get_settings

    s = get_settings()
    if s.storage_backend == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region, s.s3_object_lock)
    from app.storage.local import LocalStorage

    return LocalStorage(s.storage_root)
