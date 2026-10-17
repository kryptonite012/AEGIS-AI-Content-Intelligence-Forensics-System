"""Evidence acquisition, versioning, integrity verification and redaction.

Recording a hash proves only that AEGIS can later detect changes to the stored bytes. It says
nothing about the file's origin or authenticity before acquisition.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from aegis_ml.audio.analysis import ffprobe
from aegis_ml.core import Modality
from aegis_ml.evidence.sniff import UnsafeFileError, sniff
from aegis_ml.text.extract import extract_text
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, conflict
from app.models import EvidenceItem, EvidenceVersion, FileHash, Investigation, Membership, User
from app.security.deps import Principal
from app.services import investigations as cases
from app.services.notifications import notify
from app.services.scanning import scan_file
from app.storage.base import ObjectExists, evidence_key, get_storage

MAX_MEDIA_SECONDS = {Modality.AUDIO: 3 * 3600, Modality.VIDEO: 2 * 3600}
TEXT_MODALITIES = {Modality.TEXT, Modality.DOCUMENT}


def sanitise_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFC", base)
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().lstrip(".")
    return (base or "evidence")[:200]


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _validate_structure(path: Path, mime: str, modality: Modality) -> dict[str, Any]:
    """Parse the file with the same parser analysis will use; reject anything malformed."""
    meta: dict[str, Any] = {}
    try:
        if modality == Modality.IMAGE:
            from aegis_ml.image.analysis import exif_summary, open_image

            img = open_image(path)
            exif = exif_summary(img)
            meta = {
                "width": img.width,
                "height": img.height,
                "exif": "absent" if not exif else ("malformed" if exif.get("_status") else "present"),
                "icc_profile": "present" if img.info.get("icc_profile") else "absent",
                "xmp": "present" if (img.info.get("xmp") or img.info.get("XML:com.adobe.xmp")) else "absent",
            }
        elif mime == "application/pdf":
            from pypdf import PdfReader

            r = PdfReader(str(path))
            if r.is_encrypted:
                raise bad_request("Encrypted PDFs are not supported.", "unsupported_media")
            meta = {
                "pages": len(r.pages),
                "document_info": "present" if r.metadata else "absent",
                "xmp": "present" if r.xmp_metadata else "absent",
            }
        elif mime.endswith("wordprocessingml.document"):
            import docx

            d = docx.Document(str(path))
            cp = d.core_properties
            meta = {
                "paragraphs": len(d.paragraphs),
                "core_properties": "present" if (cp.author or cp.created or cp.last_modified_by) else "absent",
            }
        elif modality in (Modality.AUDIO, Modality.VIDEO):
            probe = ffprobe(path)
            kinds = {s.get("codec_type") for s in probe.get("streams", [])}
            needed = "video" if modality == Modality.VIDEO else "audio"
            if needed not in kinds:
                raise bad_request(f"No {needed} stream could be decoded.", "malformed_media")
            duration = float(probe.get("format", {}).get("duration") or 0)
            if duration <= 0:
                raise bad_request("Media duration could not be determined.", "malformed_media")
            if duration > MAX_MEDIA_SECONDS[modality]:
                raise bad_request(
                    f"Media longer than {MAX_MEDIA_SECONDS[modality] // 3600} h is not accepted.", "media_too_long"
                )
            meta = {
                "duration_seconds": duration,
                "streams": sorted(k for k in kinds if k),
                "container_tags": "present" if probe.get("format", {}).get("tags") else "absent",
            }
        else:
            meta = {"encoding": "validated during extraction"}
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure means the file is rejected
        raise bad_request(f"File could not be parsed as {mime}: {type(exc).__name__}.", "malformed_media") from exc
    return meta


def _store(db_org: uuid.UUID, src: Path | None, data: bytes | None, sha: str, kind: str, mime: str) -> str:
    key = evidence_key(str(db_org), sha, kind)
    storage = get_storage()
    try:
        if src is not None:
            storage.put_file(key, src, mime)
        else:
            storage.put_bytes(key, data or b"", mime)
    except ObjectExists:
        pass  # content-addressed: identical bytes are already stored write-once
    return key


def _add_version(
    db: Session,
    item: EvidenceItem,
    kind: str,
    sha: str,
    size: int,
    mime: str,
    key: str,
    user: User,
    parent: EvidenceVersion | None = None,
    transformations: list[str] | None = None,
    metadata_status: dict | None = None,
    scan_status: str = "not_applicable",
    filename: str | None = None,
    reason: str | None = None,
) -> EvidenceVersion:
    n = db.execute(
        select(func.coalesce(func.max(EvidenceVersion.version_no), 0)).where(
            EvidenceVersion.evidence_item_id == item.id
        )
    ).scalar_one()
    v = EvidenceVersion(
        id=uuid.uuid4(),
        evidence_item_id=item.id,
        version_no=n + 1,
        kind=kind,
        parent_version_id=parent.id if parent else None,
        sha256=sha,
        size_bytes=size,
        mime_type=mime,
        storage_key=key,
        original_filename=filename,
        transformations=transformations or [],
        metadata_status=metadata_status or {},
        scan_status=scan_status,
        reason=reason,
        created_by_id=user.id,
    )
    db.add(v)
    db.flush()
    db.add(
        FileHash(evidence_version_id=v.id, algorithm="sha256", value=sha, purpose="acquisition", computed_by_id=user.id)
    )
    return v


def ingest(
    db: Session,
    p: Principal,
    inv: Investigation,
    path: Path,
    filename: str,
    *,
    role: str = "primary",
    description: str | None = None,
    demo_fixture: bool = False,
) -> EvidenceItem:
    if inv.status not in cases.EVIDENCE_MUTABLE_STATES:
        raise conflict(f"Evidence cannot be added while the investigation is {inv.status}.")
    if role not in ("primary", "process_evidence"):
        raise bad_request("role must be 'primary' or 'process_evidence'.")
    s = get_settings()
    try:
        sn = sniff(path)
    except UnsafeFileError as exc:
        audit.record(
            db,
            "evidence.rejected",
            "investigation",
            inv.id,
            actor=p.user,
            organization_id=p.org_id,
            investigation_id=inv.id,
            details={"filename": sanitise_filename(filename), "reason": str(exc)},
            ip=p.ip,
        )
        db.commit()
        raise AppError(415, "unsupported_media", f"File rejected: {exc}.") from exc
    sha, size = sha256_file(path)
    if sn.modality in TEXT_MODALITIES and size > s.max_text_upload_mb * 1024 * 1024:
        raise AppError(413, "payload_too_large", f"Text and document uploads are limited to {s.max_text_upload_mb} MB.")
    scan_status, scan_detail = scan_file(path)
    if scan_status == "infected":
        audit.record(
            db,
            "evidence.rejected_malware",
            "investigation",
            inv.id,
            actor=p.user,
            organization_id=p.org_id,
            investigation_id=inv.id,
            details={"sha256": sha, "signature": scan_detail},
            ip=p.ip,
        )
        db.commit()
        raise AppError(422, "malware_detected", "The file was rejected by the malware scanner.")
    if s.require_malware_scan and scan_status != "clean":
        raise AppError(503, "scanner_required", f"Malware scanning is required but unavailable: {scan_detail}")
    meta = _validate_structure(path, sn.mime_type, sn.modality)
    name = sanitise_filename(filename)
    item = EvidenceItem(
        id=uuid.uuid4(),
        investigation_id=inv.id,
        organization_id=inv.organization_id,
        display_name=name,
        role=role,
        modality=str(sn.modality),
        mime_type=sn.mime_type,
        description=description,
        uploaded_by_id=p.user.id,
        is_demo_fixture=demo_fixture,
    )
    db.add(item)
    db.flush()
    key = _store(inv.organization_id, path, None, sha, "original", sn.mime_type)
    original = _add_version(
        db,
        item,
        "original",
        sha,
        size,
        sn.mime_type,
        key,
        p.user,
        filename=name,
        metadata_status={"detected_as": sn.detail, **meta},
        scan_status=scan_status,
        transformations=[],
    )
    derived = []
    if sn.modality in TEXT_MODALITIES:
        try:
            ex = extract_text(path, sn.mime_type)
        except Exception as exc:  # noqa: BLE001
            raise bad_request(f"Text extraction failed: {type(exc).__name__}.", "extraction_failed") from exc
        data = ex.text.encode("utf-8")
        tsha = hashlib.sha256(data).hexdigest()
        tkey = _store(inv.organization_id, None, data, tsha, "derived", "text/plain")
        _add_version(
            db,
            item,
            "normalized_text",
            tsha,
            len(data),
            "text/plain; charset=utf-8",
            tkey,
            p.user,
            parent=original,
            transformations=[ex.method, *ex.transformations],
        )
        item.extraction = ex.to_dict()
        derived.append("normalized_text")
    elif sn.modality == Modality.IMAGE:
        from PIL import Image, ImageOps

        with Image.open(path) as img:
            thumb = ImageOps.exif_transpose(img).convert("RGB")
            thumb.thumbnail((512, 512))
            buf = io.BytesIO()
            thumb.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        tsha = hashlib.sha256(data).hexdigest()
        tkey = _store(inv.organization_id, None, data, tsha, "derived", "image/png")
        _add_version(
            db,
            item,
            "thumbnail",
            tsha,
            len(data),
            "image/png",
            tkey,
            p.user,
            parent=original,
            transformations=["EXIF orientation applied", "converted to RGB", "downscaled to <=512 px", "PNG"],
        )
        derived.append("thumbnail")
    audit.record(
        db,
        "evidence.acquired",
        "evidence_item",
        item.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={
            "sha256": sha,
            "size_bytes": size,
            "mime_type": sn.mime_type,
            "filename": name,
            "role": role,
            "scan_status": scan_status,
            "derived_versions": derived,
        },
    )
    cases.advance_if(db, inv, {"draft"}, "evidence_acquired")
    return item


def current_original(item: EvidenceItem) -> EvidenceVersion:
    return next(v for v in item.versions if v.kind == "original")


def text_version(item: EvidenceItem) -> EvidenceVersion | None:
    texts = [v for v in item.versions if v.kind in ("normalized_text", "redacted") and v.purged_at is None]
    return texts[0] if texts else None


def verify_integrity(db: Session, p: Principal | None, item: EvidenceItem) -> dict[str, Any]:
    storage = get_storage()
    results = []
    mismatch = False
    for v in item.versions:
        if v.purged_at is not None:
            results.append({"version_id": str(v.id), "version_no": v.version_no, "kind": v.kind, "status": "purged"})
            continue
        try:
            actual, size = storage.sha256(v.storage_key)
            ok = actual == v.sha256 and size == v.size_bytes
        except Exception:  # noqa: BLE001 - a missing object is an integrity failure
            actual, ok = None, False
        mismatch |= not ok
        db.add(
            FileHash(
                evidence_version_id=v.id,
                algorithm="sha256",
                value=actual or "missing",
                purpose="integrity_check",
                matches_recorded=ok,
                computed_by_id=p.user.id if p else None,
            )
        )
        results.append(
            {
                "version_id": str(v.id),
                "version_no": v.version_no,
                "kind": v.kind,
                "recorded": v.sha256,
                "recomputed": actual,
                "matches": ok,
            }
        )
    if mismatch:
        item.status = "integrity_alert"
        audit.record(
            db,
            "evidence.integrity_mismatch",
            "evidence_item",
            item.id,
            actor=p.user if p else None,
            organization_id=item.organization_id,
            investigation_id=item.investigation_id,
            details={"results": results},
        )
        recipients = {item.uploaded_by_id}
        recipients |= set(
            db.execute(
                select(Membership.user_id).where(
                    Membership.organization_id == item.organization_id,
                    Membership.role_id.in_(("org_admin", "system_admin")),
                )
            ).scalars()
        )
        for uid in recipients:
            notify(
                db,
                uid,
                item.organization_id,
                "integrity_alert",
                f"Integrity alert: {item.display_name}",
                "The stored evidence no longer matches its recorded SHA-256 hash. It must not be treated as unchanged.",
                link=f"/cases/{item.investigation_id}?evidence={item.id}",
                severity="critical",
            )
    else:
        audit.record(
            db,
            "evidence.integrity_verified",
            "evidence_item",
            item.id,
            actor=p.user if p else None,
            organization_id=item.organization_id,
            investigation_id=item.investigation_id,
            details={"versions_checked": len(results)},
        )
    return {
        "evidence_id": str(item.id),
        "intact": not mismatch,
        "status": item.status,
        "versions": results,
        "note": "A matching hash shows the stored bytes are unchanged since acquisition by AEGIS. It does not "
        "establish the file's origin or authenticity.",
    }


def redact_text(
    db: Session, p: Principal, item: EvidenceItem, spans: list[tuple[int, int]], reason: str
) -> EvidenceVersion:
    base = text_version(item)
    if base is None:
        raise bad_request("Only evidence with extracted text can be redacted.")
    with get_storage().local_path(base.storage_key) as path:
        text = path.read_text("utf-8")
    chars = list(text)
    for start, end in sorted(spans):
        if not (0 <= start < end <= len(chars)):
            raise bad_request(f"Span {start}-{end} is outside the text.")
        for i in range(start, end):
            if not chars[i].isspace():
                chars[i] = "█"
    data = "".join(chars).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    key = _store(item.organization_id, None, data, sha, "derived", "text/plain")
    v = _add_version(
        db,
        item,
        "redacted",
        sha,
        len(data),
        "text/plain; charset=utf-8",
        key,
        p.user,
        parent=base,
        transformations=[f"redacted {len(spans)} span(s)"],
        reason=reason,
    )
    audit.record(
        db,
        "evidence.redacted",
        "evidence_item",
        item.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=item.investigation_id,
        reason=reason,
        details={"new_version_id": str(v.id), "parent_version_id": str(base.id), "spans": len(spans)},
    )
    return v


def purge_binaries(db: Session, item: EvidenceItem, actor: User, reason: str) -> int:
    """Retention purge: remove stored bytes but keep the hash records and tombstones."""
    from app.db import utcnow

    n = 0
    storage = get_storage()
    for v in item.versions:
        if v.purged_at is None:
            other = db.execute(
                select(func.count())
                .select_from(EvidenceVersion)
                .where(
                    EvidenceVersion.storage_key == v.storage_key,
                    EvidenceVersion.purged_at.is_(None),
                    EvidenceVersion.id != v.id,
                )
            ).scalar_one()
            if not other:
                storage.purge(v.storage_key)
            v.purged_at = utcnow()
            n += 1
    item.status = "purged"
    audit.record(
        db,
        "evidence.purged",
        "evidence_item",
        item.id,
        actor=actor,
        organization_id=item.organization_id,
        investigation_id=item.investigation_id,
        reason=reason,
        details={"versions_purged": n},
    )
    return n


def copy_upload_to_temp(src, dest: Path, limit_bytes: int) -> tuple[str, int]:
    """Stream an upload to disk enforcing a byte limit; returns (sha256, size)."""
    h = hashlib.sha256()
    n = 0
    with dest.open("wb") as out:
        while chunk := src.read(1 << 20):
            n += len(chunk)
            if n > limit_bytes:
                raise AppError(413, "payload_too_large", f"Upload exceeds the {limit_bytes // (1024 * 1024)} MB limit.")
            h.update(chunk)
            out.write(chunk)
    return h.hexdigest(), n
