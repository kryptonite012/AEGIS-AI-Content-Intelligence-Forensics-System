"""SQLAlchemy models. UUID primary keys everywhere except the audit sequence number."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(default=utcnow, nullable=False)


# --------------------------------------------------------------------------- identity


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    allow_external_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column()
    last_login_at: Mapped[datetime | None] = mapped_column()
    is_demo_account: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    created_at: Mapped[datetime] = _created()
    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship()


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------- cases


class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        UniqueConstraint("organization_id", "case_reference"),
        Index("ix_investigations_org_status", "organization_id", "status"),
    )
    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    case_reference: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    purpose: Mapped[str] = mapped_column(Text)
    media_category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    legal_basis: Mapped[str | None] = mapped_column(Text)
    retention_class: Mapped[str] = mapped_column(String(40), default="standard")
    access_classification: Mapped[str] = mapped_column(String(40), default="standard")
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_external_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    disposition: Mapped[str | None] = mapped_column(String(80))
    pending_questions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_demo_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column()
    assigned_reviewer: Mapped[User | None] = relationship(foreign_keys=[assigned_reviewer_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    evidence_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_items.id"))
    detector_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("detector_runs.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30), default="note")  # note|finding|question|contradiction
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    author: Mapped[User] = relationship()


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(60))
    rationale: Mapped[str] = mapped_column(Text)
    agrees_with_automated: Mapped[bool | None] = mapped_column(Boolean)
    automated_outcome: Mapped[str | None] = mapped_column(String(80))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_decisions.id"))
    content_sha256: Mapped[str] = mapped_column(String(64))
    audit_event_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    reviewer: Mapped[User] = relationship()


class Appeal(Base):
    __tablename__ = "appeals"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id"))
    submitted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    on_behalf_of: Mapped[str | None] = mapped_column(String(200))  # free text; minimal personal data
    grounds: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")  # open|under_review|upheld|corrected|rejected
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column()


# --------------------------------------------------------------------------- evidence


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="primary")  # primary | process_evidence
    modality: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="active")  # active|integrity_alert|purged
    description: Mapped[str | None] = mapped_column(Text)
    acquired_at: Mapped[datetime] = _created()
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_demo_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    versions: Mapped[list[EvidenceVersion]] = relationship(
        back_populates="item", order_by="EvidenceVersion.version_no", foreign_keys="EvidenceVersion.evidence_item_id"
    )
    uploaded_by: Mapped[User] = relationship()


class EvidenceVersion(Base):
    __tablename__ = "evidence_versions"
    __table_args__ = (UniqueConstraint("evidence_item_id", "version_no"),)
    id: Mapped[uuid.UUID] = _uuid()
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))  # original|normalized_text|thumbnail|redacted|correction
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_versions.id"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(400))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    transformations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    metadata_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    scan_status: Mapped[str] = mapped_column(String(60), default="not_scanned")
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    purged_at: Mapped[datetime | None] = mapped_column()
    item: Mapped[EvidenceItem] = relationship(back_populates="versions", foreign_keys=[evidence_item_id])


class FileHash(Base):
    __tablename__ = "file_hashes"
    id: Mapped[uuid.UUID] = _uuid()
    evidence_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_versions.id"), index=True)
    algorithm: Mapped[str] = mapped_column(String(20), default="sha256")
    value: Mapped[str] = mapped_column(String(128), index=True)
    purpose: Mapped[str] = mapped_column(String(30))  # acquisition | integrity_check
    matches_recorded: Mapped[bool | None] = mapped_column(Boolean)
    computed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    computed_at: Mapped[datetime] = _created()


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="primary")
    total_size: Mapped[int] = mapped_column(BigInteger)
    received: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = _created()


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|executed|blocked
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column()
    executed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- analysis


class ModelProvider(Base):
    __tablename__ = "model_providers"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # local | external
    external_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class DetectorVersion(Base):
    """Model registry record."""

    __tablename__ = "detector_versions"
    __table_args__ = (UniqueConstraint("method_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid()
    method_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("model_providers.id"))
    model_identifier: Mapped[str | None] = mapped_column(String(300))
    license: Mapped[str | None] = mapped_column(String(200))
    supported_media: Mapped[list[str]] = mapped_column(JSONType, default=list)
    languages_evaluated: Mapped[list[str]] = mapped_column(JSONType, default=list)
    minimum_input: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    known_limitations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    data_documentation: Mapped[str | None] = mapped_column(Text)
    evidence_class: Mapped[str] = mapped_column(String(40))
    implementation_status: Mapped[str] = mapped_column(String(40))
    validation_status: Mapped[str] = mapped_column(String(30), default="unvalidated")
    validation_benchmark_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("benchmark_runs.id"))
    validation_note: Mapped[str | None] = mapped_column(Text)
    calibration_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calibration_profiles.id"))
    operating_threshold: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = _created()


class CalibrationProfile(Base):
    __tablename__ = "calibration_profiles"
    id: Mapped[uuid.UUID] = _uuid()
    method_id: Mapped[str] = mapped_column(String(80), index=True)
    method_version: Mapped[str] = mapped_column(String(60))
    calibration_method: Mapped[str] = mapped_column(String(30))  # platt | threshold_only
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    threshold: Mapped[float | None] = mapped_column(Float)
    target_fpr: Mapped[float | None] = mapped_column(Float)
    population: Mapped[str] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(JSONType, default=list)
    benchmark_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("benchmark_runs.id"))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (Index("ix_analysis_jobs_status", "status"),)
    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    evidence_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_versions.id"))
    profile_id: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    methods_total: Mapped[int] = mapped_column(Integer, default=0)
    methods_done: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    external_processing_permitted: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    task_id: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    fusion: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    runs: Mapped[list[DetectorRun]] = relationship(back_populates="job", order_by="DetectorRun.position")


class DetectorRun(Base):
    __tablename__ = "detector_runs"
    __table_args__ = (UniqueConstraint("job_id", "method_id"),)
    id: Mapped[uuid.UUID] = _uuid()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    method_id: Mapped[str] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(40))
    method_name: Mapped[str] = mapped_column(String(200))
    evidence_class: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    input_sha256: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    threshold: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[str] = mapped_column(String(60), default="aegis.method_result/v1")
    score: Mapped[float | None] = mapped_column(Float)
    score_semantics: Mapped[str | None] = mapped_column(Text)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    flagged: Mapped[bool | None] = mapped_column(Boolean)
    uncertainty: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    limitations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    job: Mapped[AnalysisJob] = relationship(back_populates="runs")
    segments: Mapped[list[SegmentFinding]] = relationship(cascade="all, delete-orphan")
    artifacts: Mapped[list[AnalysisArtifact]] = relationship(cascade="all, delete-orphan")


class AnalysisSignal(Base):
    """Structured observation record used by evidence fusion."""

    __tablename__ = "analysis_signals"
    id: Mapped[uuid.UUID] = _uuid()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    detector_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detector_runs.id", ondelete="CASCADE"), unique=True)
    evidence_class: Mapped[str] = mapped_column(String(40))
    verification_status: Mapped[str | None] = mapped_column(String(60))
    calibration_status: Mapped[str] = mapped_column(String(30))  # validated | uncalibrated | not_applicable
    applicable_population: Mapped[str | None] = mapped_column(Text)
    input_characteristics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    uncertainty: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    known_dependencies: Mapped[list[str]] = mapped_column(JSONType, default=list)
    supporting_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class SegmentFinding(Base):
    __tablename__ = "segment_findings"
    id: Mapped[uuid.UUID] = _uuid()
    detector_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detector_runs.id", ondelete="CASCADE"), index=True)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80))
    score: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class AnalysisArtifact(Base):
    __tablename__ = "analysis_artifacts"
    id: Mapped[uuid.UUID] = _uuid()
    detector_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detector_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(80))
    storage_key: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    cannot_establish: Mapped[str] = mapped_column(Text)


class ProvenanceRecord(Base):
    __tablename__ = "provenance_records"
    id: Mapped[uuid.UUID] = _uuid()
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    detector_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detector_runs.id", ondelete="CASCADE"), unique=True)
    standard: Mapped[str] = mapped_column(String(40), default="c2pa")
    state: Mapped[str] = mapped_column(String(60))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    trust_anchor: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- research


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(60))
    modality: Mapped[str] = mapped_column(String(20), default="text")
    provenance: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(String(200))
    consent_basis: Mapped[str] = mapped_column(Text)
    documentation: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(400))
    n_samples: Mapped[int] = mapped_column(Integer)
    splits: Mapped[dict[str, int]] = mapped_column(JSONType, default=dict)
    fields: Mapped[list[str]] = mapped_column(JSONType, default=list)
    duplicate_report: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class BenchmarkSuite(Base):
    __tablename__ = "benchmark_suites"
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id"))
    task: Mapped[str] = mapped_column(String(60))  # method_on_dataset | imported_scores | reference_watermark
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        CheckConstraint(
            "result_kind in ('published','reproduced','locally_measured','simulated','vendor_reported')",
            name="result_kind",
        ),
    )
    id: Mapped[uuid.UUID] = _uuid()
    suite_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("benchmark_suites.id"))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id"))
    method_id: Mapped[str] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(40))
    result_kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    source_citation: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column()


class BenchmarkSample(Base):
    __tablename__ = "benchmark_samples"
    __table_args__ = (UniqueConstraint("run_id", "sample_key", "transform"),)
    id: Mapped[uuid.UUID] = _uuid()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    sample_key: Mapped[str] = mapped_column(String(120))
    split: Mapped[str] = mapped_column(String(20), default="test")
    label: Mapped[int] = mapped_column(Integer)
    group: Mapped[str | None] = mapped_column(String(80))
    transform: Mapped[str] = mapped_column(String(60), default="original")
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30))


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    id: Mapped[uuid.UUID] = _uuid()
    experiment_id: Mapped[str] = mapped_column(String(60), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # analytical | simulation
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    results: Mapped[Any] = mapped_column(JSONType)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- reports, audit, governance


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("investigation_id", "version"),)
    id: Mapped[uuid.UUID] = _uuid()
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | final | superseded
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id"))
    correction_reason: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(30), default="aegis.report/v1")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    json_sha256: Mapped[str] = mapped_column(String(64))
    pdf_storage_key: Mapped[str | None] = mapped_column(String(400))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    generated_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = _created()
    finalized_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    finalized_at: Mapped[datetime | None] = mapped_column()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_time", "organization_id", "occurred_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = _created()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (UniqueConstraint("organization_id", "classification"),)
    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    classification: Mapped[str] = mapped_column(String(40))
    retain_days: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class SystemHealthEvent(Base):
    __tablename__ = "system_health_events"
    id: Mapped[uuid.UUID] = _uuid()
    component: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"),)
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column()


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
