"""Reproducible forensic reports (JSON schema ``aegis.report/v1`` + PDF).

The JSON payload is canonicalised and hashed; the PDF is rendered from the payload alone with
ReportLab's invariant mode, so the same payload always produces the same bytes. Automated
findings and human conclusions are kept in separate sections.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.audit import service as audit
from app.audit.service import canonical
from app.core.config import get_settings
from app.core.errors import AppError, conflict
from app.db import utcnow
from app.models import (
    AnalysisJob,
    Annotation,
    Appeal,
    AuditEvent,
    EvidenceItem,
    Investigation,
    Report,
    ReviewDecision,
    User,
)
from app.security.deps import Principal
from app.services import investigations as cases
from app.storage.base import ObjectExists, get_storage

SCHEMA = "aegis.report/v1"

STANDARD_LIMITATIONS = [
    "No detector can reliably establish authorship or origin from content alone. Statistical outputs describe "
    "resemblance to known generator behaviour under the stated conditions.",
    "A low or negative detector output does not prove human authorship; absence of a watermark or provenance "
    "record does not indicate either AI generation or human creation.",
    "Detector performance varies with length, language, domain, generator, editing, compression and other "
    "transformations; uncalibrated scores are not probabilities.",
    "A valid provenance signature shows the record is intact and "
    "signed; it does not establish that its claims are true.",
    "Hash records show the stored bytes are unchanged since acquisition by AEGIS; they do not establish origin.",
    "This report supports investigation and review. It must not by itself be the basis of an adverse decision "
    "about any person; independent corroboration and qualified human review are required.",
]


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def build_payload(
    db: Session,
    inv: Investigation,
    report_id: uuid.UUID,
    version: int,
    generated_by: User,
    supersedes: Report | None,
    correction_reason: str | None,
) -> dict[str, Any]:
    items = (
        db.execute(
            select(EvidenceItem).where(EvidenceItem.investigation_id == inv.id).order_by(EvidenceItem.acquired_at)
        )
        .scalars()
        .all()
    )
    jobs = (
        db.execute(select(AnalysisJob).where(AnalysisJob.investigation_id == inv.id).order_by(AnalysisJob.created_at))
        .scalars()
        .all()
    )
    reviews = (
        db.execute(
            select(ReviewDecision).where(ReviewDecision.investigation_id == inv.id).order_by(ReviewDecision.created_at)
        )
        .scalars()
        .all()
    )
    notes = (
        db.execute(select(Annotation).where(Annotation.investigation_id == inv.id).order_by(Annotation.created_at))
        .scalars()
        .all()
    )
    appeals = db.execute(select(Appeal).where(Appeal.investigation_id == inv.id)).scalars().all()
    events = (
        db.execute(select(AuditEvent).where(AuditEvent.investigation_id == inv.id).order_by(AuditEvent.seq))
        .scalars()
        .all()
    )
    users = {u.id: u for u in db.execute(select(User)).scalars()}

    def who(uid: uuid.UUID | None) -> str | None:
        return users[uid].display_name if uid in users else None

    evidence = []
    for it in items:
        evidence.append(
            {
                "evidence_id": str(it.id),
                "display_name": it.display_name,
                "role": it.role,
                "modality": it.modality,
                "mime_type": it.mime_type,
                "status": it.status,
                "acquired_at": _iso(it.acquired_at),
                "uploaded_by": who(it.uploaded_by_id),
                "demo_fixture": it.is_demo_fixture,
                "extraction": {
                    k: (it.extraction or {}).get(k)
                    for k in ("method", "token_count", "tokenizer", "language", "warnings", "ocr_derived", "pages")
                }
                if it.extraction
                else None,
                "versions": [
                    {
                        "version_id": str(v.id),
                        "version_no": v.version_no,
                        "kind": v.kind,
                        "sha256": v.sha256,
                        "size_bytes": v.size_bytes,
                        "mime_type": v.mime_type,
                        "parent_version_id": str(v.parent_version_id) if v.parent_version_id else None,
                        "transformations": v.transformations,
                        "metadata_status": v.metadata_status,
                        "scan_status": v.scan_status,
                        "created_at": _iso(v.created_at),
                        "purged": v.purged_at is not None,
                    }
                    for v in it.versions
                ],
            }
        )
    analyses = []
    for j in jobs:
        analyses.append(
            {
                "job_id": str(j.id),
                "evidence_id": str(j.evidence_item_id),
                "evidence_version_id": str(j.evidence_version_id),
                "profile": j.profile_id,
                "status": j.status,
                "requested_by": who(j.requested_by_id),
                "created_at": _iso(j.created_at),
                "finished_at": _iso(j.finished_at),
                "external_processing_permitted": j.external_processing_permitted,
                "automated_assessment": j.fusion,
                "methods": [
                    {
                        "run_id": str(r.id),
                        "method_id": r.method_id,
                        "method_name": r.method_name,
                        "method_version": r.method_version,
                        "evidence_class": r.evidence_class,
                        "status": r.status,
                        "input_sha256": r.input_sha256,
                        "config": r.config,
                        "threshold": r.threshold,
                        "summary": r.summary,
                        "score": r.score,
                        "score_semantics": r.score_semantics,
                        "calibrated": r.calibrated,
                        "flagged": r.flagged,
                        "uncertainty": r.uncertainty,
                        "warnings": r.warnings,
                        "limitations": r.limitations,
                        "output_schema": r.output_schema,
                        "started_at": _iso(r.started_at),
                        "finished_at": _iso(r.finished_at),
                        "artifacts": [
                            {
                                "name": a.name,
                                "sha256": a.sha256,
                                "description": a.description,
                                "cannot_establish": a.cannot_establish,
                            }
                            for a in r.artifacts
                        ],
                        "segment_count": len(r.segments),
                        "provenance": r.output if r.evidence_class == "cryptographic_provenance" else None,
                    }
                    for r in j.runs
                ],
            }
        )
    contradictions = sorted({m for j in jobs for m in ((j.fusion or {}).get("conflicting") or [])})
    head = events[-1].event_hash if events else None
    return {
        "schema": SCHEMA,
        "report": {
            "report_id": str(report_id),
            "version": version,
            "generated_at": utcnow().isoformat(),
            "generated_by": generated_by.display_name,
            "aegis_version": __version__,
            "deployment_mode": str(get_settings().mode),
            "supersedes_report_id": str(supersedes.id) if supersedes else None,
            "correction_reason": correction_reason,
        },
        "case": {
            "investigation_id": str(inv.id),
            "case_reference": inv.case_reference,
            "title": inv.title,
            "purpose": inv.purpose,
            "media_category": inv.media_category,
            "description": inv.description,
            "priority": inv.priority,
            "status": inv.status,
            "legal_basis": inv.legal_basis,
            "retention_class": inv.retention_class,
            "access_classification": inv.access_classification,
            "assigned_reviewer": who(inv.assigned_reviewer_id),
            "created_by": who(inv.created_by_id),
            "created_at": _iso(inv.created_at),
            "demo_fixture": inv.is_demo_fixture,
            "pending_questions": inv.pending_questions,
        },
        "scope_and_methodology": {
            "description": "Evidence was acquired into a write-once store with SHA-256 hashing. Analyses ran as "
            "persisted background jobs; each method's version, configuration and input hash are listed. "
            "Signals were combined only by the documented evidence-fusion policy, which does not average "
            "or multiply scores across detectors.",
            "fusion_policy": "aegis-fusion-v1",
        },
        "evidence_inventory": evidence,
        "automated_findings": analyses,
        "contradictory_signals": contradictions,
        "human_assessment": {
            "note": "Human conclusions below are separate from automated findings.",
            "review_decisions": [
                {
                    "decision_id": str(r.id),
                    "reviewer": who(r.reviewer_id),
                    "decision": r.decision,
                    "rationale": r.rationale,
                    "agrees_with_automated": r.agrees_with_automated,
                    "automated_outcome": r.automated_outcome,
                    "content_sha256": r.content_sha256,
                    "audit_event_hash": r.audit_event_hash,
                    "recorded_at": _iso(r.created_at),
                }
                for r in reviews
            ],
            "annotations": [
                {"kind": a.kind, "author": who(a.author_id), "body": a.body, "created_at": _iso(a.created_at)}
                for a in notes
            ],
        },
        "appeals": [
            {
                "appeal_id": str(a.id),
                "status": a.status,
                "grounds": a.grounds,
                "resolution": a.resolution,
                "created_at": _iso(a.created_at),
            }
            for a in appeals
        ],
        "limitations": STANDARD_LIMITATIONS,
        "audit_references": {
            "event_count": len(events),
            "chain_head_for_case": head,
            "events": [
                {
                    "seq": e.seq,
                    "action": e.action,
                    "occurred_at": _iso(e.occurred_at),
                    "actor": e.actor_label,
                    "event_hash": e.event_hash,
                }
                for e in events[-200:]
            ],
        },
    }


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def generate(
    db: Session,
    p: Principal,
    inv: Investigation,
    correction_of: Report | None = None,
    correction_reason: str | None = None,
) -> Report:
    latest = db.execute(
        select(func.coalesce(func.max(Report.version), 0)).where(Report.investigation_id == inv.id)
    ).scalar_one()
    if correction_of is None and inv.status in cases.LOCKED_STATES:
        raise conflict("A finalised investigation's report can only be changed through a correction.")
    rid = uuid.uuid4()
    payload = build_payload(db, inv, rid, latest + 1, p.user, correction_of, correction_reason)
    digest = payload_sha256(payload)
    pdf = render_pdf(payload, digest)
    pdf_sha = hashlib.sha256(pdf).hexdigest()
    key = f"orgs/{inv.organization_id}/reports/{rid}.pdf"
    try:
        get_storage().put_bytes(key, pdf, "application/pdf")
    except ObjectExists as exc:  # pragma: no cover - ids are unique
        raise AppError(500, "storage_conflict", "Report object already exists.") from exc
    rep = Report(
        id=rid,
        investigation_id=inv.id,
        version=latest + 1,
        status="draft",
        supersedes_id=correction_of.id if correction_of else None,
        correction_reason=correction_reason,
        schema_version=SCHEMA,
        payload=payload,
        json_sha256=digest,
        pdf_storage_key=key,
        pdf_sha256=pdf_sha,
        generated_by_id=p.user.id,
    )
    db.add(rep)
    db.flush()
    audit.record(
        db,
        "report.generated",
        "report",
        rep.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        reason=correction_reason,
        details={
            "version": rep.version,
            "json_sha256": digest,
            "pdf_sha256": pdf_sha,
            "supersedes": str(correction_of.id) if correction_of else None,
        },
    )
    return rep


def finalize(db: Session, p: Principal, inv: Investigation, rep: Report) -> Report:
    if rep.status != "draft":
        raise conflict(f"Report is {rep.status}.")
    has_review = db.execute(
        select(func.count()).select_from(ReviewDecision).where(ReviewDecision.investigation_id == inv.id)
    ).scalar_one()
    if not has_review:
        raise conflict("A human review decision is required before a report can be finalised.")
    if rep.generated_by_id == p.user.id and not p.user.is_system_admin:
        raise conflict("Separation of duties: the report must be finalised by someone other than its author.")
    rep.status, rep.finalized_at, rep.finalized_by_id = "final", utcnow(), p.user.id
    if rep.supersedes_id:
        old = db.get(Report, rep.supersedes_id)
        if old is not None:
            old.status = "superseded"
    if inv.status in ("human_review", "inconclusive"):
        cases.transition(db, inv, "report_finalized", actor=p)
    audit.record(
        db,
        "report.finalized",
        "report",
        rep.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={"version": rep.version, "json_sha256": rep.json_sha256, "pdf_sha256": rep.pdf_sha256},
    )
    return rep


def verify(rep: Report) -> dict[str, Any]:
    json_ok = payload_sha256(rep.payload) == rep.json_sha256
    pdf_ok = None
    if rep.pdf_storage_key:
        try:
            actual, _ = get_storage().sha256(rep.pdf_storage_key)
            pdf_ok = actual == rep.pdf_sha256
        except Exception:  # noqa: BLE001
            pdf_ok = False
    rerender_ok = hashlib.sha256(render_pdf(rep.payload, rep.json_sha256)).hexdigest() == rep.pdf_sha256
    return {
        "report_id": str(rep.id),
        "json_integrity": json_ok,
        "pdf_integrity": pdf_ok,
        "pdf_reproducible_from_json": rerender_ok,
        "json_sha256": rep.json_sha256,
        "pdf_sha256": rep.pdf_sha256,
        "intact": bool(json_ok and pdf_ok is not False and rerender_ok),
    }


# --------------------------------------------------------------------------- PDF


def render_pdf(payload: dict[str, Any], digest: str) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    midnight, blue, grey = colors.HexColor("#0B1220"), colors.HexColor("#2563EB"), colors.HexColor("#5B6475")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12.5, alignment=TA_LEFT)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=10, textColor=grey)
    mono = ParagraphStyle("m", parent=body, fontName="Courier", fontSize=7, leading=9, wordWrap="CJK")
    h1 = ParagraphStyle(
        "h1",
        parent=ss["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=midnight,
        spaceBefore=10,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, textColor=blue, spaceBefore=8, spaceAfter=4
    )
    cover_title = ParagraphStyle("ct", parent=h1, fontSize=24, leading=30, textColor=midnight)

    def P(text: Any, style=body) -> Paragraph:  # type: ignore[no-untyped-def]
        return Paragraph(escape("" if text is None else str(text)), style)

    def table(rows: list[list[Any]], widths: list[float], header: bool = True) -> Table:
        data = (
            [[c if isinstance(c, Paragraph) else P(c, small if i else body) for c in row] for i, row in enumerate(rows)]
            if header
            else [[c if isinstance(c, Paragraph) else P(c) for c in r] for r in rows]
        )
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0, splitByRow=1)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D1E0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF9"))]
        t.setStyle(TableStyle(style))
        return t

    W = A4[0] - 36 * mm
    r, case = payload["report"], payload["case"]
    story: list[Any] = []
    story += [
        Spacer(1, 40 * mm),
        P("AEGIS", ParagraphStyle("brand", parent=h2, fontSize=12, textColor=blue)),
        P("Forensic Analysis Report", cover_title),
        Spacer(1, 4 * mm),
        P(case["title"], ParagraphStyle("t2", parent=h2, textColor=midnight, fontSize=13)),
        Spacer(1, 10 * mm),
        table(
            [
                ["Field", "Value"],
                ["Case reference", case["case_reference"]],
                ["Report ID", r["report_id"]],
                ["Report version", r["version"]],
                ["Generated", r["generated_at"]],
                ["Generated by", r["generated_by"]],
                ["Deployment mode", r["deployment_mode"]],
                ["Access classification", case["access_classification"]],
                ["Payload SHA-256", P(digest, mono)],
            ],
            [45 * mm, W - 45 * mm],
        ),
    ]
    if case.get("demo_fixture"):
        story += [Spacer(1, 6 * mm), P("DEMO FIXTURE — this case uses synthetic demonstration data.", h2)]
    if r.get("supersedes_report_id"):
        story += [
            Spacer(1, 4 * mm),
            P(f"Correction of report {r['supersedes_report_id']}: {r.get('correction_reason')}"),
        ]
    story += [
        Spacer(1, 10 * mm),
        P(
            "This report distinguishes automated findings from human conclusions. Automated "
            "outcomes describe the evidence; they are not findings of misconduct.",
            small,
        ),
        PageBreak(),
    ]

    story.append(P("1. Executive summary", h1))
    outcomes = [a["automated_assessment"] for a in payload["automated_findings"] if a.get("automated_assessment")]
    if outcomes:
        for a, o in zip(payload["automated_findings"], outcomes, strict=False):
            story.append(P(f"Evidence {a['evidence_id'][:8]} — automated outcome: {o.get('primary_label')}.", body))
            for reason in (o.get("uncertainty_reasons") or [])[:4]:
                story.append(P(f"• {reason}", small))
    else:
        story.append(P("No completed analyses."))
    reviews = payload["human_assessment"]["review_decisions"]
    story.append(Spacer(1, 3 * mm))
    story.append(
        P(
            "Human assessment: "
            + (f"{reviews[-1]['decision']} (reviewer: {reviews[-1]['reviewer']})." if reviews else "not yet recorded."),
            body,
        )
    )

    story.append(P("2. Scope and methodology", h1))
    story.append(P(payload["scope_and_methodology"]["description"]))
    story.append(P(f"Case purpose: {case['purpose']}"))
    if case.get("legal_basis"):
        story.append(P(f"Recorded legal or organisational basis: {case['legal_basis']}"))

    story.append(P("3. Evidence inventory and hashes", h1))
    rows = [["Evidence", "Version", "Kind", "SHA-256", "Size", "Scan"]]
    for e in payload["evidence_inventory"]:
        for v in e["versions"]:
            rows.append(
                [
                    f"{e['display_name']} ({e['role']})",
                    v["version_no"],
                    v["kind"],
                    P(v["sha256"], mono),
                    v["size_bytes"],
                    v["scan_status"],
                ]
            )
    story.append(table(rows, [42 * mm, 13 * mm, 22 * mm, W - 125 * mm, 20 * mm, 28 * mm]))

    story.append(P("4. Processing history and method versions", h1))
    rows = [["Job", "Method", "Version", "Class", "Status"]]
    for a in payload["automated_findings"]:
        for m in a["methods"]:
            rows.append([a["job_id"][:8], m["method_name"], m["method_version"], m["evidence_class"], m["status"]])
    story.append(table(rows, [16 * mm, W - 106 * mm, 18 * mm, 42 * mm, 30 * mm]))

    story.append(P("5. Individual results", h1))
    for a in payload["automated_findings"]:
        story.append(P(f"Job {a['job_id']} — profile {a['profile']} — {a['status']}", h2))
        for m in a["methods"]:
            block = [
                P(f"{m['method_name']} [{m['status']}]", ParagraphStyle("mh", parent=body, fontName="Helvetica-Bold")),
                P(m.get("summary") or ""),
            ]
            if m.get("score") is not None:
                block.append(
                    P(
                        f"Output: {m['score']:.4g} ({m.get('score_semantics')}); calibrated: {m['calibrated']}; "
                        f"interpreted flag: {m['flagged']}",
                        small,
                    )
                )
            for w in (m.get("warnings") or [])[:5]:
                block.append(P(f"Warning: {w}", small))
            story.append(KeepTogether(block + [Spacer(1, 2 * mm)]))

    story.append(P("6. Statistical reliability", h1))
    story.append(
        P(
            "Statistical outputs are interpreted only when a calibration profile validated on held-out data "
            "exists for the method and population. Outputs without one are reported but not interpreted. "
            "Deployment PPV depends on prevalence and must be computed for the screening population "
            "(Research Bench › Base-rate calculator)."
        )
    )

    story.append(P("7. Provenance findings", h1))
    prov = [m for a in payload["automated_findings"] for m in a["methods"] if m.get("provenance")]
    if prov:
        for m in prov:
            pv = m["provenance"]
            story.append(P(f"{m['summary']} State: {pv.get('state')}."))
    else:
        story.append(
            P(
                "No provenance verification was run, or no supported provenance record was found. This does "
                "not indicate AI generation or human creation."
            )
        )

    story.append(P("8. Contradictory signals", h1))
    story.append(P(", ".join(payload["contradictory_signals"]) or "None identified by the fusion policy."))

    story.append(P("9. Limitations", h1))
    for lim in payload["limitations"]:
        story.append(P(f"• {lim}"))

    story.append(P("10. Human reviewer assessment", h1))
    story.append(P(payload["human_assessment"]["note"], small))
    if reviews:
        for rv in reviews:
            story.append(
                KeepTogether(
                    [
                        P(
                            f"{rv['decision']} — {rv['reviewer']} — {rv['recorded_at']}",
                            ParagraphStyle("rv", parent=body, fontName="Helvetica-Bold"),
                        ),
                        P(rv["rationale"]),
                        P(f"Decision hash {rv['content_sha256']}", mono),
                    ]
                )
            )
    else:
        story.append(P("No human review decision has been recorded."))
    if payload["human_assessment"]["annotations"]:
        story.append(P("Annotations", h2))
        for an in payload["human_assessment"]["annotations"][:100]:
            story.append(P(f"[{an['kind']}] {an['author']}: {an['body']}", small))

    story.append(P("Appendix A. Audit references", h1))
    ar = payload["audit_references"]
    story.append(P(f"{ar['event_count']} audit events reference this case. Latest event hash:"))
    story.append(P(ar.get("chain_head_for_case") or "—", mono))
    rows = [["Seq", "Action", "Time", "Actor"]] + [
        [e["seq"], e["action"], e["occurred_at"], e["actor"]] for e in ar["events"][-60:]
    ]
    story.append(table(rows, [14 * mm, 55 * mm, 55 * mm, W - 124 * mm]))

    def frame(canvas, doc):  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(grey)
        canvas.drawString(
            18 * mm, 10 * mm, f"AEGIS report {r['report_id']} · v{r['version']} · {case['case_reference']}"
        )
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(blue)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, A4[1] - 12 * mm, A4[0] - 18 * mm, A4[1] - 12 * mm)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"AEGIS report {case['case_reference']}",
        author="AEGIS",
        subject="Forensic analysis report",
        invariant=1,
        creator="AEGIS report generator",
    )
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
