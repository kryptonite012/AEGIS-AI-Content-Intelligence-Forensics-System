from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.storage.base import ObjectExists, Storage, StorageError


class LocalStorage(Storage):
    """Filesystem store. Files are written via a temp file + atomic rename and set read-only.
    Keys are validated so they can never escape the root directory."""

    name = "local-filesystem"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in key.split("/") or "\\" in key or "\0" in key:
            raise StorageError("invalid storage key")
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise StorageError("invalid storage key")
        return p

    def _write(self, key: str, writer) -> None:  # type: ignore[no-untyped-def]
        dest = self._path(key)
        if dest.exists():
            raise ObjectExists(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".partial")
        writer(tmp)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IRGRP)
        try:
            os.link(tmp, dest)  # fails if dest exists: no overwrite race
        except FileExistsError as exc:
            raise ObjectExists(key) from exc
        finally:
            tmp.unlink(missing_ok=True)

    def put_file(self, key: str, src: Path, content_type: str) -> None:
        self._write(key, lambda tmp: shutil.copyfile(src, tmp))

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._write(key, lambda tmp: tmp.write_bytes(data))

    def open(self, key: str) -> Iterator[bytes]:
        p = self._path(key)
        if not p.is_file():
            raise StorageError("object not found")
        with p.open("rb") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        p = self._path(key)
        if not p.is_file():
            raise StorageError("object not found")
        yield p

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def purge(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
            p.unlink()

    def health(self) -> tuple[bool, str]:
        try:
            probe = self.root / ".health"
            probe.write_text("ok")
            probe.unlink()
            usage = shutil.disk_usage(self.root)
            return True, f"writable; {usage.free // (1024**3)} GiB free"
        except OSError as exc:
            return False, f"not writable: {exc.strerror}"
