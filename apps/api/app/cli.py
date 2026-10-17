"""Operational commands.

python -m app.cli sync                 # roles/permissions + model registry records
python -m app.cli create-admin --email ... --name ... --org-name ... --org-slug ...
python -m app.cli seed-demo            # development only: demo org, users and DEMO FIXTURE cases
python -m app.cli benchmark            # built-in simulated reference-watermark benchmark + experiments
python -m app.cli verify-audit
python -m app.cli verify-evidence      # recompute every stored hash
python -m app.cli recover-jobs
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db import get_sessionmaker, session_scope


def _principal(db, user, org):  # type: ignore[no-untyped-def]
    from app.models import Membership
    from app.security.deps import Principal
    from app.security.permissions import role_permissions

    m = db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org.id)
    ).scalar_one()
    return Principal(user, uuid.uuid4(), org, m.role_id, role_permissions(m.role_id), None)


def cmd_sync(_: argparse.Namespace) -> None:
    from app.services.bootstrap import sync_registry, sync_roles

    with session_scope() as db:
        sync_roles(db)
        sync_registry(db)
    print("roles, permissions and model registry synchronised")


def _ensure_org(db, name: str, slug: str):  # type: ignore[no-untyped-def]
    from app.models import Organization, RetentionPolicy

    org = db.execute(select(Organization).where(Organization.slug == slug)).scalar_one_or_none()
    if org is None:
        org = Organization(name=name, slug=slug)
        db.add(org)
        db.flush()
        for cls, days in (("standard", 365), ("extended", 365 * 7), ("legal_minimum", 90), ("research", 365 * 3)):
            db.add(
                RetentionPolicy(
                    organization_id=org.id,
                    classification=cls,
                    retain_days=days,
                    description="Default template; requires review by the organisation.",
                )
            )
    return org


def _ensure_user(
    db,
    org,
    email: str,
    name: str,
    role: str,
    password: str,
    demo: bool = False,  # type: ignore[no-untyped-def]
    system_admin: bool = False,
):
    from app.models import Membership, User
    from app.security.passwords import hash_password

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            display_name=name,
            password_hash=hash_password(password),
            is_demo_account=demo,
            is_system_admin=system_admin,
        )
        db.add(user)
        db.flush()
    if not db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org.id)
    ).first():
        db.add(Membership(user_id=user.id, organization_id=org.id, role_id=role))
    return user


def cmd_create_admin(a: argparse.Namespace) -> None:
    from app.audit import service as audit
    from app.security.passwords import password_problems

    cmd_sync(a)
    password = os.environ.get("AEGIS_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if problems := password_problems(password):
        sys.exit("Password " + "; ".join(problems))
    with session_scope() as db:
        org = _ensure_org(db, a.org_name, a.org_slug)
        user = _ensure_user(db, org, a.email.lower(), a.name, "system_admin", password, system_admin=True)
        audit.record(db, "admin.bootstrap_admin", "user", user.id, actor_label="cli", organization_id=org.id)
    print(f"system administrator {a.email} ready in organisation {a.org_slug}")


DEMO_USERS = [
    ("admin@aegis.demo", "Demo System Administrator", "system_admin"),
    ("orgadmin@aegis.demo", "Demo Organisation Administrator", "org_admin"),
    ("investigator@aegis.demo", "Demo Investigator", "investigator"),
    ("analyst@aegis.demo", "Demo Forensic Analyst", "forensic_analyst"),
    ("reviewer@aegis.demo", "Demo Independent Reviewer", "independent_reviewer"),
    ("auditor@aegis.demo", "Demo Auditor", "auditor"),
    ("researcher@aegis.demo", "Demo Researcher", "researcher"),
]


def cmd_seed_demo(a: argparse.Namespace) -> None:
    s = get_settings()
    if s.is_production:
        sys.exit("seed-demo is disabled in production.")
    from aegis_ml import fixtures
    from aegis_ml.text.reference_watermark import generate_reference_text

    from app.models import EvidenceItem, Investigation
    from app.services import analysis as an
    from app.services import investigations as cases
    from app.services.evidence import ingest

    cmd_sync(a)
    password = os.environ.get("AEGIS_DEMO_PASSWORD", "Aegis-Demo-Only-2026")
    with session_scope() as db:
        org = _ensure_org(db, "AEGIS Demo Laboratory", "demo-lab")
        users = {
            role: _ensure_user(db, org, email, name, role, password, demo=True, system_admin=role == "system_admin")
            for email, name, role in DEMO_USERS
        }
    Session_ = get_sessionmaker()
    created = []
    with Session_() as db, tempfile.TemporaryDirectory() as td:
        from app.models import Organization, User

        org = db.execute(select(Organization).where(Organization.slug == "demo-lab")).scalar_one()
        inv_user = db.get(User, users["investigator"].id)
        reviewer = db.get(User, users["independent_reviewer"].id)
        p = _principal(db, inv_user, org)
        tdp = Path(td)
        key = os.environ.get("AEGIS_REFERENCE_WATERMARK_KEY", "")
        specs = [
            (
                "DEMO-TXT-001",
                "DEMO FIXTURE — Field-notes authorship triage",
                "text",
                "Demonstrate text triage on synthetic demo documents.",
                [
                    ("field-notes.txt", lambda p_: p_.write_text(fixtures.HUMAN_STYLE_SAMPLE * 2), "text_triage"),
                    (
                        "reference-watermarked.txt",
                        (lambda p_: p_.write_text(generate_reference_text(key.encode(), 220, 7)))
                        if len(key) >= 16
                        else None,
                        "text_triage",
                    ),
                    (
                        "field-notes.docx",
                        lambda p_: fixtures.make_docx(p_, fixtures.HUMAN_STYLE_SAMPLE.split(". ")),
                        "text_triage",
                    ),
                ],
            ),
            (
                "DEMO-IMG-001",
                "DEMO FIXTURE — Image provenance check",
                "image",
                "Demonstrate Content Credentials verification and image observations on synthetic images.",
                [
                    ("signed-generated.jpg", lambda p_: fixtures.make_c2pa_signed_jpeg(p_, tdp), "image_investigation"),
                    (
                        "test-pattern.jpg",
                        lambda p_: fixtures.make_jpeg(p_, exif_software="DemoCam 1.0"),
                        "image_investigation",
                    ),
                    ("declared-generator.png", fixtures.make_png_with_declaration, "image_investigation"),
                ],
            ),
            (
                "DEMO-AV-001",
                "DEMO FIXTURE — Audio and video structure review",
                "mixed",
                "Demonstrate audio and video processing on generated tones and test patterns.",
                [
                    ("tone.wav", fixtures.make_wav, "synthetic_speech"),
                    ("test-pattern.mp4", fixtures.make_mp4, "deepfake_video"),
                ],
            ),
        ]
        for ref, title, media, purpose, files in specs:
            if db.execute(
                select(Investigation).where(
                    Investigation.organization_id == org.id, Investigation.case_reference == ref
                )
            ).first():
                continue
            inv = Investigation(
                organization_id=org.id,
                created_by_id=inv_user.id,
                case_reference=ref,
                title=title,
                purpose=purpose,
                media_category=media,
                is_demo_fixture=True,
                description="All evidence in this case is synthetic and generated by the AEGIS demo seeder.",
                assigned_reviewer_id=reviewer.id,
                legal_basis="Demonstration only; no personal data.",
            )
            db.add(inv)
            db.flush()
            from app.audit import service as audit

            audit.record(
                db,
                "investigation.created",
                "investigation",
                inv.id,
                actor=inv_user,
                organization_id=org.id,
                investigation_id=inv.id,
                details={"demo_fixture": True},
            )
            jobs = []
            for fname, maker, profile in files:
                if maker is None:
                    continue
                path = tdp / fname
                maker(path)
                item = ingest(db, p, inv, path, fname, demo_fixture=True)
                db.flush()
                jobs.append(an.create_job(db, p, inv, db.get(EvidenceItem, item.id), profile))
            db.commit()
            for j in jobs:
                an.execute_job(j.id)
            db.refresh(inv)
            if inv.status == "analysis_complete" and ref == "DEMO-TXT-001":
                cases.transition(db, inv, "human_review", actor=p)
                db.commit()
            created.append(ref)
    print(
        json.dumps(
            {
                "organisation": "demo-lab",
                "users": [u[0] for u in DEMO_USERS],
                "password": "value of AEGIS_DEMO_PASSWORD (default documented in README; development only)",
                "cases_created": created,
            },
            indent=2,
        )
    )


def cmd_benchmark(a: argparse.Namespace) -> None:
    from aegis_research.experiments.__main__ import run as run_experiments

    from app.models import User
    from app.services.benchmarks import run_reference_watermark_benchmark

    out = Path(a.out)
    with get_sessionmaker()() as db:
        user = db.execute(select(User).where(User.is_system_admin.is_(True))).scalars().first()
        if user is None:
            sys.exit("Create an administrator first (create-admin or seed-demo).")
        run = run_reference_watermark_benchmark(db, user, None)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"benchmark-{run.id}.json").write_text(
            json.dumps(
                {
                    "result_kind": run.result_kind,
                    "status": run.status,
                    "manifest": run.manifest,
                    "metrics": run.metrics,
                    "error": run.error,
                },
                indent=2,
                default=str,
            )
        )
        overall = (run.metrics or {}).get("overall") or {}
        print(
            f"[{run.result_kind}] reference watermark benchmark {run.status}: AUROC={overall.get('auroc')} "
            f"n={overall.get('n')} -> {out}"
        )
    run_experiments(
        list(__import__("aegis_research.experiments", fromlist=["EXPERIMENTS"]).EXPERIMENTS),
        out / "experiments",
        plots=a.plots,
    )


def cmd_verify_audit(_: argparse.Namespace) -> None:
    from app.audit.service import verify_chain

    with get_sessionmaker()() as db:
        r = verify_chain(db)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["valid"] else 1)


def cmd_verify_evidence(_: argparse.Namespace) -> None:
    from app.models import EvidenceItem
    from app.services.evidence import verify_integrity

    bad = 0
    with session_scope() as db:
        for item in db.execute(select(EvidenceItem).where(EvidenceItem.status != "purged")).scalars():
            r = verify_integrity(db, None, item)
            bad += not r["intact"]
            print(f"{'OK      ' if r['intact'] else 'MISMATCH'} {item.id} {item.display_name}")
    sys.exit(1 if bad else 0)


def cmd_recover(_: argparse.Namespace) -> None:
    from app.services.analysis import recover_stale_jobs

    with get_sessionmaker()() as db:
        print(f"{recover_stale_jobs(db)} stale job(s) handled")


def main() -> None:
    p = argparse.ArgumentParser(prog="aegis")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    ca = sub.add_parser("create-admin")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--org-name", required=True)
    ca.add_argument("--org-slug", required=True)
    ca.set_defaults(fn=cmd_create_admin)
    sub.add_parser("seed-demo").set_defaults(fn=cmd_seed_demo)
    b = sub.add_parser("benchmark")
    b.add_argument("--out", default="benchmarks/runs")
    b.add_argument("--plots", action="store_true")
    b.set_defaults(fn=cmd_benchmark)
    sub.add_parser("verify-audit").set_defaults(fn=cmd_verify_audit)
    sub.add_parser("verify-evidence").set_defaults(fn=cmd_verify_evidence)
    sub.add_parser("recover-jobs").set_defaults(fn=cmd_recover)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
