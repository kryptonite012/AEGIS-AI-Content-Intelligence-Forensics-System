"""Shared types for analysis methods."""

from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class EvidenceClass(StrEnum):
    """Different forms of evidence. They are never interchangeable and never averaged."""

    STATISTICAL_INFERENCE = "statistical_inference"
    VERIFIED_WATERMARK = "verified_watermark"
    CRYPTOGRAPHIC_PROVENANCE = "cryptographic_provenance"
    MEDIA_FORENSIC_OBSERVATION = "media_forensic_observation"
    DECLARED_METADATA = "declared_metadata"  # unsigned claims embedded in the file
    PROCESS_EVIDENCE = "process_evidence"  # drafts, revision history, notes
    HUMAN_ASSESSMENT = "human_assessment"


class ImplementationStatus(StrEnum):
    OPERATIONAL = "operational"  # implemented and runnable with bundled dependencies
    REQUIRES_CONFIGURATION = "requires_configuration"  # real adapter; needs model weights/credentials
    EXPERIMENTAL = "experimental"  # implemented but not validated
    PLACEHOLDER = "placeholder"  # integration boundary only; never produces results


class RunStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # not configured / dependency missing - NOT a negative result
    INSUFFICIENT_INPUT = "insufficient_input"
    UNSUPPORTED_INPUT = "unsupported_input"
    FAILED = "failed"  # error during execution - NOT a negative result
    BLOCKED_BY_POLICY = "blocked_by_policy"  # e.g. external processing disabled


@dataclass(frozen=True)
class MethodInfo:
    id: str
    name: str
    version: str
    modalities: tuple[Modality, ...]
    evidence_class: EvidenceClass
    implementation: ImplementationStatus
    description: str
    output_semantics: str
    limitations: tuple[str, ...]
    references: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()  # configuration keys / optional packages
    external_processing: bool = False  # True if evidence leaves the deployment
    validated_granularity: tuple[str, ...] = ()  # e.g. ("document",)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modalities"] = [str(m) for m in self.modalities]
        return d


@dataclass
class Segment:
    start: float  # char offset (text) or seconds (audio/video) or frame index
    end: float
    unit: str
    label: str
    score: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    """A derived visualisation (e.g. spectrum image). Stored as a processing derivative, never
    as a replacement for the original evidence."""

    name: str
    media_type: str
    data: bytes
    description: str
    cannot_establish: str


@dataclass
class MethodResult:
    method_id: str
    method_version: str
    evidence_class: EvidenceClass
    status: RunStatus
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    score_semantics: str | None = None
    calibrated: bool = False
    flagged: bool | None = None  # only set when a validated operating threshold exists
    uncertainty: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    error: str | None = None

    def to_dict(self, include_artifacts: bool = False) -> dict[str, Any]:
        d = asdict(self)
        d["evidence_class"] = str(self.evidence_class)
        d["status"] = str(self.status)
        if not include_artifacts:
            d["artifacts"] = [
                {k: v for k, v in a.items() if k != "data"} for a in d["artifacts"]
            ]
        return d


@dataclass
class AnalysisInput:
    """Everything a method may read. Paths point at server-side processing copies."""

    modality: Modality
    mime_type: str
    original_path: Path
    sha256: str
    text: str | None = None  # extracted text for text methods
    language: str | None = None
    extraction: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    allow_external_processing: bool = False


class AnalysisMethod(ABC):
    info: MethodInfo

    def availability(self) -> tuple[bool, str]:
        """Whether the method can run here. Must be cheap and side-effect free."""
        return True, "available"

    def supports(self, inp: AnalysisInput) -> bool:
        return inp.modality in self.info.modalities

    @abstractmethod
    def _run(self, inp: AnalysisInput) -> MethodResult: ...

    def result(self, status: RunStatus, summary: str, **kw: Any) -> MethodResult:
        kw.setdefault("limitations", list(self.info.limitations))
        return MethodResult(self.info.id, self.info.version, self.info.evidence_class, status, summary, **kw)

    def run(self, inp: AnalysisInput) -> MethodResult:
        """Run with uniform handling of unavailability, policy and failures."""
        started = time.monotonic()
        if not self.supports(inp):
            res = self.result(RunStatus.UNSUPPORTED_INPUT, f"{self.info.name} does not support {inp.mime_type}.")
        elif self.info.external_processing and not inp.allow_external_processing:
            res = self.result(
                RunStatus.BLOCKED_BY_POLICY,
                "External processing is disabled for this investigation; evidence was not sent.",
            )
        else:
            ok, reason = self.availability()
            if not ok:
                res = self.result(RunStatus.UNAVAILABLE, reason)
            else:
                try:
                    res = self._run(inp)
                except Exception as exc:  # noqa: BLE001 - failures become explicit FAILED results
                    res = self.result(
                        RunStatus.FAILED,
                        f"{self.info.name} failed: {type(exc).__name__}",
                        error="".join(traceback.format_exception_only(type(exc), exc)).strip()[:2000],
                    )
        res.duration_ms = int((time.monotonic() - started) * 1000)
        return res
