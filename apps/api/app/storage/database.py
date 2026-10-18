from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.storage.base import ObjectExists, Storage, StorageError, check_key

CHUNK = 1 << 20


class DatabaseStorage(Storage):
    """PostgreSQL store for hosts without a persistent disk (for example free container platforms,
    whose filesystem is reset on every restart). An object's header and ordered chunks are inserted in
    one transaction, so readers see all of it or none; a second write to the same key fails on the
    primary key. Database backups then cover the evidence too. Intended for small deployments."""

    name = "database"

    def __init__(self, engine=None) -> None:  # type: ignore[no-untyped-def]
        from app.db import get_engine

        self.engine = engine or get_engine()

    def _write(self, key: str, size: int, chunks: Iterable[bytes], content_type: str) -> None:
        from app.db import utcnow
        from app.models import StoredObject, StoredObjectChunk

        check_key(key)
        with self.engine.begin() as c:
            created = c.execute(
                insert(StoredObject)
                .values(key=key, content_type=content_type, size_bytes=size, created_at=utcnow())
                .on_conflict_do_nothing(index_elements=["key"])
                .returning(StoredObject.key)
            ).first()
            if created is None:
                raise ObjectExists(key)
            for seq, chunk in enumerate(chunks):
                c.execute(insert(StoredObjectChunk).values(key=key, seq=seq, data=chunk))

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        def chunks() -> Iterator[bytes]:
            with open(src, "rb") as f:
                while chunk := f.read(CHUNK):
                    yield chunk

        self._write(key, os.path.getsize(src), chunks(), content_type)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._write(key, len(data), (data[i : i + CHUNK] for i in range(0, len(data), CHUNK)), content_type)

    def open(self, key: str) -> Iterator[bytes]:
        from app.models import StoredObjectChunk

        check_key(key)
        if not self.exists(key):
            raise StorageError("object not found")
        with self.engine.connect() as c:
            rows = c.execution_options(stream_results=True, yield_per=4).execute(
                select(StoredObjectChunk.data).where(StoredObjectChunk.key == key).order_by(StoredObjectChunk.seq)
            )
            for (data,) in rows:
                yield bytes(data)

    def exists(self, key: str) -> bool:
        from app.models import StoredObject

        check_key(key)
        with self.engine.connect() as c:
            return c.execute(select(StoredObject.key).where(StoredObject.key == key)).first() is not None

    def purge(self, key: str) -> None:
        from app.models import StoredObject

        check_key(key)
        with self.engine.begin() as c:
            c.execute(delete(StoredObject).where(StoredObject.key == key))

    def health(self) -> tuple[bool, str]:
        from app.models import StoredObject

        try:
            with self.engine.connect() as c:
                n, size = c.execute(select(func.count(), func.coalesce(func.sum(StoredObject.size_bytes), 0))).one()
            return True, f"{n} object(s), {size / (1 << 20):.1f} MiB in PostgreSQL"
        except Exception as exc:  # noqa: BLE001
            return False, f"object table unavailable: {type(exc).__name__}"
