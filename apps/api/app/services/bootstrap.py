"""Idempotent bootstrap: roles/permissions and model-registry records for every registered method."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DetectorVersion, ModelProvider, Permission, Role, RolePermission
from app.security.permissions import PERMISSIONS, ROLES
from app.services.analysis import registry


def sync_roles(db: Session) -> None:
    for pid, desc in PERMISSIONS.items():
        if db.get(Permission, pid) is None:
            db.add(Permission(id=pid, description=desc))
    db.flush()
    for rid, (name, desc, perms) in ROLES.items():
        role = db.get(Role, rid) or Role(id=rid)
        role.display_name, role.description = name, desc
        db.add(role)
        db.flush()
        existing = set(db.execute(select(RolePermission.permission_id).where(RolePermission.role_id == rid)).scalars())
        for p in perms - existing:
            db.add(RolePermission(role_id=rid, permission_id=p))
        for p in existing - perms:
            db.delete(db.get(RolePermission, (rid, p)))


def sync_registry(db: Session) -> None:
    for pid, name, kind, ext in (
        ("aegis-local", "AEGIS built-in (local)", "local", False),
        ("operator-local-model", "Operator-supplied local model", "local", False),
        ("external-http", "External detection service", "external", True),
    ):
        if db.get(ModelProvider, pid) is None:
            db.add(ModelProvider(id=pid, name=name, kind=kind, external_processing=ext))
    db.flush()
    for m in registry().values():
        info = m.info
        rec = db.execute(
            select(DetectorVersion).where(DetectorVersion.method_id == info.id, DetectorVersion.version == info.version)
        ).scalar_one_or_none()
        provider = (
            "external-http"
            if info.external_processing
            else ("operator-local-model" if info.implementation == "requires_configuration" else "aegis-local")
        )
        if rec is None:
            rec = DetectorVersion(method_id=info.id, version=info.version, validation_status="unvalidated")
            db.add(rec)
        rec.name = info.name
        rec.provider_id = provider
        rec.supported_media = [str(x) for x in info.modalities]
        rec.known_limitations = list(info.limitations)
        rec.evidence_class = str(info.evidence_class)
        rec.implementation_status = str(info.implementation)
        rec.data_documentation = "; ".join(info.references) or None
        rec.minimum_input = rec.minimum_input or (
            {"tokens": 50} if "text" in rec.supported_media and info.evidence_class == "statistical_inference" else {}
        )
