"""Evidence Fusion Service (decision policy ``aegis-fusion-v1``).

The policy never averages or multiplies scores across detectors. It sorts observations by evidence
class, notes which are completed, interpretable (validated threshold), missing or failed, detects
contradictions, and assigns descriptive outcome categories. Combination of statistical signals
into a single probability is deliberately NOT performed: no held-out joint validation exists for
any detector pair in this deployment, and detector dependence is unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

POLICY_ID = "aegis-fusion-v1"


class Outcome(StrEnum):
    NO_RELIABLE_CONCLUSION = "no_reliable_conclusion"
    INCONCLUSIVE = "inconclusive"
    SOME_SIGNALS_CONSISTENT_WITH_AI = "some_signals_consistent_with_ai"
    MULTIPLE_SIGNALS_CONSISTENT_WITH_AI = "multiple_compatible_signals_consistent_with_ai"
    RECOGNIZED_WATERMARK = "evidence_of_recognized_watermark"
    PROVENANCE_VERIFIED = "provenance_record_verified"
    PROVENANCE_FAILED = "provenance_verification_failed"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


OUTCOME_LABELS = {
    Outcome.NO_RELIABLE_CONCLUSION: "No reliable conclusion",
    Outcome.INCONCLUSIVE: "Inconclusive",
    Outcome.SOME_SIGNALS_CONSISTENT_WITH_AI: "Some signals consistent with AI generation",
    Outcome.MULTIPLE_SIGNALS_CONSISTENT_WITH_AI: "Multiple compatible signals consistent with AI generation",
    Outcome.RECOGNIZED_WATERMARK: "Evidence of a recognized watermark",
    Outcome.PROVENANCE_VERIFIED: "Provenance record verified",
    Outcome.PROVENANCE_FAILED: "Provenance verification failed",
    Outcome.CONTRADICTORY_EVIDENCE: "Contradictory evidence — review the discrepancy",
    Outcome.HUMAN_REVIEW_REQUIRED: "Human review required",
}


@dataclass
class FusionResult:
    policy: str
    primary_outcome: str
    primary_label: str
    categories: list[str]
    requires_human_review: bool
    agreeing: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)
    missing: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    not_interpreted: list[str] = field(default_factory=list)
    calibration_applies: bool = False
    uncertainty_reasons: list[str] = field(default_factory=list)
    suggested_next_steps: list[str] = field(default_factory=list)
    by_class: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    statement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fuse(results: list[dict[str, Any]]) -> FusionResult:
    """``results`` are serialised MethodResult dicts (as stored by the API)."""
    by_class: dict[str, list[dict[str, Any]]] = {}
    missing, failed, not_interpreted = [], [], []
    flagged_stat, unflagged_stat = [], []
    watermark_detected, watermark_checked = [], []
    prov_verified = prov_failed = None
    prov_declares_capture = prov_declares_ai = False
    declared_ai = []

    for r in results:
        cls, status, mid = r["evidence_class"], r["status"], r["method_id"]
        by_class.setdefault(cls, []).append(
            {
                "method_id": mid,
                "status": status,
                "summary": r.get("summary"),
                "flagged": r.get("flagged"),
                "calibrated": r.get("calibrated", False),
            }
        )
        if status in ("unavailable", "blocked_by_policy"):
            missing.append({"method_id": mid, "reason": r.get("summary", "")})
            continue
        if status == "failed":
            failed.append({"method_id": mid, "reason": r.get("summary", "")})
            continue
        if status != "completed":
            continue
        out = r.get("output") or {}
        if cls == "statistical_inference":
            if r.get("flagged") is True:
                flagged_stat.append(mid)
            elif r.get("flagged") is False:
                unflagged_stat.append(mid)
            else:
                not_interpreted.append(mid)
        elif cls == "verified_watermark":
            watermark_checked.append(mid)
            if r.get("flagged") is True:
                watermark_detected.append(mid)
        elif cls == "cryptographic_provenance":
            state = out.get("state")
            if state in ("signature_valid_signer_trusted", "signature_valid_signer_untrusted"):
                prov_verified = {"method_id": mid, "trusted": state == "signature_valid_signer_trusted"}
                prov_declares_capture = bool(out.get("declared_capture_source"))
                prov_declares_ai = bool(out.get("declared_ai_source"))
            elif state == "verification_failed":
                prov_failed = mid
        elif cls == "declared_metadata" and (out.get("generator_markers") or out.get("declares_ai_source_type")):
            declared_ai.append(mid)

    categories: list[Outcome] = []
    agreeing: list[str] = []
    conflicting: list[str] = []
    reasons: list[str] = []
    steps: list[str] = []

    if prov_verified:
        categories.append(Outcome.PROVENANCE_VERIFIED)
        if not prov_verified["trusted"]:
            reasons.append("The provenance signature validates but the signer is not in this deployment's trust list.")
    if prov_failed:
        categories.append(Outcome.PROVENANCE_FAILED)
        steps.append(
            "Obtain an original copy from the source; verification failure may indicate modification after signing."
        )
    if watermark_detected:
        categories.append(Outcome.RECOGNIZED_WATERMARK)
    ai_indicators = (
        flagged_stat
        + watermark_detected
        + declared_ai
        + ([prov_verified["method_id"]] if prov_verified and prov_declares_ai else [])
    )
    if len(flagged_stat) >= 2:
        categories.append(Outcome.MULTIPLE_SIGNALS_CONSISTENT_WITH_AI)
        reasons.append(
            "Statistical detectors may share training data or failure modes; their dependence is "
            "unknown, so agreement is not treated as independent corroboration."
        )
    elif len(flagged_stat) == 1:
        categories.append(Outcome.SOME_SIGNALS_CONSISTENT_WITH_AI)
    agreeing.extend(ai_indicators)

    # Contradictions: signed capture claim vs AI indicators, or AI flag vs non-flag among validated detectors.
    if prov_verified and prov_declares_capture and (flagged_stat or watermark_detected):
        conflicting.extend([prov_verified["method_id"], *flagged_stat, *watermark_detected])
        reasons.append(
            "A validated provenance record declares a capture pathway while other signals are consistent "
            "with AI generation. The provenance record is not rejected automatically; the discrepancy "
            "requires review."
        )
    if flagged_stat and unflagged_stat:
        conflicting.extend([*flagged_stat, *unflagged_stat])
        reasons.append("Validated statistical detectors disagree.")
    if conflicting:
        categories.append(Outcome.CONTRADICTORY_EVIDENCE)

    any_interpretable = bool(flagged_stat or unflagged_stat or watermark_checked or prov_verified or prov_failed)
    if not categories:
        if any_interpretable:
            categories.append(Outcome.INCONCLUSIVE)
            reasons.append(
                "No interpretable signal is consistent with AI generation. A negative or low result does "
                "not establish human authorship."
            )
        else:
            categories.append(Outcome.NO_RELIABLE_CONCLUSION)
            reasons.append("No method with a validated interpretation produced a result for this evidence.")
    if not_interpreted:
        reasons.append(
            f"{len(not_interpreted)} statistical output(s) have no validated operating threshold and are "
            "shown without interpretation."
        )
        steps.append(
            "Run the detector through the Benchmark Laboratory on representative labelled data to "
            "establish a validated operating point."
        )
    if missing:
        steps.append("Configure unavailable methods if appropriate (see System Health).")
    if failed:
        reasons.append(f"{len(failed)} method(s) failed; failures are not negative results.")
        steps.append("Re-run failed methods after investigating the error.")
    if declared_ai:
        reasons.append(
            "Unsigned file metadata declares a generation tool. Such declarations are unverified claims "
            "that can be added, copied or removed; they are listed but not treated as verification."
        )
    if prov_verified and prov_declares_ai:
        reasons.append("The validated provenance record itself declares AI generation (signer's claim).")
    if watermark_checked and not watermark_detected:
        reasons.append("No supported watermark was detected. This does not indicate human authorship.")
    if not prov_verified and not prov_failed:
        steps.append("Request the original file or source records (drafts, capture devices, publication history).")
    steps.append("Collect independent process or documentary evidence before any decision affecting a person.")

    requires_review = any(
        c in categories
        for c in (
            Outcome.SOME_SIGNALS_CONSISTENT_WITH_AI,
            Outcome.MULTIPLE_SIGNALS_CONSISTENT_WITH_AI,
            Outcome.RECOGNIZED_WATERMARK,
            Outcome.PROVENANCE_FAILED,
            Outcome.CONTRADICTORY_EVIDENCE,
        )
    )
    if requires_review:
        categories.append(Outcome.HUMAN_REVIEW_REQUIRED)

    priority = [
        Outcome.CONTRADICTORY_EVIDENCE,
        Outcome.PROVENANCE_FAILED,
        Outcome.RECOGNIZED_WATERMARK,
        Outcome.MULTIPLE_SIGNALS_CONSISTENT_WITH_AI,
        Outcome.SOME_SIGNALS_CONSISTENT_WITH_AI,
        Outcome.PROVENANCE_VERIFIED,
        Outcome.INCONCLUSIVE,
        Outcome.NO_RELIABLE_CONCLUSION,
    ]
    primary = next(p for p in priority if p in categories)
    statement = (
        f"Automated outcome: {OUTCOME_LABELS[primary]}. This describes the available evidence under policy "
        f"{POLICY_ID}; it is not a finding of misconduct and does not replace qualified human review."
    )
    return FusionResult(
        policy=POLICY_ID,
        primary_outcome=str(primary),
        primary_label=OUTCOME_LABELS[primary],
        categories=[str(c) for c in categories],
        requires_human_review=True,  # every investigation in AEGIS ends with a human assessment
        agreeing=sorted(set(agreeing)),
        conflicting=sorted(set(conflicting)),
        missing=missing,
        failed=failed,
        not_interpreted=not_interpreted,
        calibration_applies=any(
            r.get("calibrated")
            for r in results
            if r["status"] == "completed" and r["evidence_class"] == "statistical_inference"
        ),
        uncertainty_reasons=reasons,
        suggested_next_steps=list(dict.fromkeys(steps)),
        by_class=by_class,
        statement=statement,
    )
