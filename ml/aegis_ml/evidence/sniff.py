"""Content-based file type identification and archive safety checks.

The declared extension and client MIME type are never trusted; only the bytes are. Only formats
with an implemented and tested parser are accepted.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from aegis_ml.core import Modality

MAX_DOCX_ENTRIES = 2000
MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class UnsafeFileError(ValueError):
    """Raised for files that must be rejected (malformed, dangerous or unsupported)."""


@dataclass(frozen=True)
class SniffResult:
    mime_type: str
    modality: Modality
    extension: str
    detail: str


SUPPORTED = {
    "text/plain": (Modality.TEXT, "txt"),
    "application/pdf": (Modality.DOCUMENT, "pdf"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (Modality.DOCUMENT, "docx"),
    "image/png": (Modality.IMAGE, "png"),
    "image/jpeg": (Modality.IMAGE, "jpg"),
    "image/webp": (Modality.IMAGE, "webp"),
    "audio/wav": (Modality.AUDIO, "wav"),
    "audio/mpeg": (Modality.AUDIO, "mp3"),
    "audio/mp4": (Modality.AUDIO, "m4a"),
    "video/mp4": (Modality.VIDEO, "mp4"),
}


def _result(mime: str, detail: str) -> SniffResult:
    modality, ext = SUPPORTED[mime]
    return SniffResult(mime, modality, ext, detail)


def _check_docx(path: Path) -> SniffResult:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise UnsafeFileError("archive has too many entries")
            total = 0
            names = set()
            for i in infos:
                n = i.filename
                if n.startswith("/") or ".." in n.split("/") or "\\" in n or ":" in n:
                    raise UnsafeFileError("archive contains an unsafe path")
                if i.flag_bits & 0x1:
                    raise UnsafeFileError("encrypted archive entries are not supported")
                total += i.file_size
                if i.compress_size and i.file_size / max(i.compress_size, 1) > MAX_COMPRESSION_RATIO:
                    raise UnsafeFileError("archive compression ratio exceeds the safety limit")
                names.add(n)
            if total > MAX_DOCX_UNCOMPRESSED:
                raise UnsafeFileError("archive expands beyond the safety limit")
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                if "word/vbaProject.bin" in names:
                    raise UnsafeFileError("macro-enabled documents are rejected")
                return _result(SUPPORTED_DOCX, "OOXML WordprocessingML package")
    except zipfile.BadZipFile as exc:
        raise UnsafeFileError("malformed ZIP container") from exc
    raise UnsafeFileError("ZIP archives other than DOCX documents are not accepted")


SUPPORTED_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _looks_like_text(head: bytes) -> str | None:
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if b"\x00" in head:
        return None
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the end of the sniff window.
        if exc.start >= len(head) - 3:
            return "utf-8"
        return None


def sniff(path: Path) -> SniffResult:
    with path.open("rb") as f:
        head = f.read(8192)
    if not head:
        raise UnsafeFileError("empty file")
    if head.startswith(b"%PDF-"):
        return _result("application/pdf", head[:8].decode("latin-1").strip())
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return _result("image/png", "PNG signature")
    if head.startswith(b"\xff\xd8\xff"):
        return _result("image/jpeg", "JPEG SOI marker")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _result("image/webp", "RIFF/WEBP")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return _result("audio/wav", "RIFF/WAVE")
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE6) in (0xE2, 0xE4, 0xE6)):
        return _result("audio/mpeg", "MPEG audio frame / ID3")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return _result("audio/mp4", f"ISO BMFF brand {brand.decode(errors='replace')}")
        if brand in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"dash", b"iso5", b"iso6", b"MSNV", b"M4V "):
            return _result("video/mp4", f"ISO BMFF brand {brand.decode(errors='replace')}")
        raise UnsafeFileError(f"unsupported ISO BMFF brand {brand!r}")
    if head.startswith(b"PK\x03\x04"):
        return _check_docx(path)
    if head.startswith((b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe")):
        raise UnsafeFileError("executable content is rejected")
    enc = _looks_like_text(head)
    if enc:
        return _result("text/plain", f"text ({enc})")
    raise UnsafeFileError("unrecognised or unsupported file format")
