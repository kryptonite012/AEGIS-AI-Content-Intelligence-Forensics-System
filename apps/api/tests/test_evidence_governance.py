"""Evidence integrity, versioning, redaction, retention, appeals, workflow rules."""

import os
import stat

from aegis_ml import fixtures
from conftest import new_case, run_job, upload


def test_integrity_verification_and_mismatch_alert(org):
    from app.db import get_sessionmaker
    from app.models import EvidenceVersion
    from app.storage.base import get_storage

    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    r = inv.post(f"/api/v1/evidence/{ev['id']}/verify").json()
    assert r["intact"] is True and all(v["matches"] for v in r["versions"])
    with get_sessionmaker()() as db:
        key = db.get(EvidenceVersion, ev["versions"][0]["id"]).storage_key
    path = get_storage().root / key
    os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
    path.write_bytes(b"silently replaced")
    r = inv.post(f"/api/v1/evidence/{ev['id']}/verify").json()
    assert r["intact"] is False and r["status"] == "integrity_alert"
    notes = org.actor("org_admin").get("/api/v1/notifications").json()
    assert any(n["severity"] == "critical" for n in notes["items"])
    # Affected evidence cannot be analysed as if unchanged.
    resp = inv.post(
        f"/api/v1/analysis/investigations/{case['id']}/jobs",
        json={"evidence_item_id": ev["id"], "profile_id": "text_triage"},
    )
    assert resp.status_code == 409


def test_storage_is_write_once():
    import pytest
    from app.storage.base import ObjectExists, get_storage

    s = get_storage()
    s.put_bytes("tests/write-once", b"a", "text/plain")
    with pytest.raises(ObjectExists):
        s.put_bytes("tests/write-once", b"b", "text/plain")
    from app.storage.base import StorageError

    with pytest.raises(StorageError):
        s.put_bytes("../escape", b"x", "text/plain")


def test_s3_backend_with_moto():
    import boto3
    import pytest
    from app.storage.s3 import S3Storage
    from moto import mock_aws

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="aegis-test")
        s = S3Storage("aegis-test", None, "us-east-1", False)
        s.put_bytes("k/1", b"hello", "text/plain")
        assert s.exists("k/1") and b"".join(s.open("k/1")) == b"hello"
        assert s.sha256("k/1")[1] == 5
        from app.storage.base import ObjectExists

        with pytest.raises(ObjectExists):
            s.put_bytes("k/1", b"other", "text/plain")
        assert s.health()[0]


def test_redaction_creates_new_version_preserving_original(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", b"Contact Ravi at 555-0100 about the river survey results. " * 4).json()
    r = inv.post(
        f"/api/v1/evidence/{ev['id']}/redactions",
        json={"spans": [[8, 12], [16, 24]], "reason": "Personal data removal"},
    )
    assert r.status_code == 201 and r.json()["kind"] == "redacted"
    full = inv.get(f"/api/v1/evidence/{ev['id']}").json()
    assert [v["kind"] for v in full["versions"]] == ["original", "normalized_text", "redacted"]
    red = inv.get(f"/api/v1/evidence/{ev['id']}/text", params={"version": "redacted"}).json()["text"]
    orig = inv.get(f"/api/v1/evidence/{ev['id']}/text").json()["text"]
    assert orig.startswith("Contact Ravi at 555-0100")
    assert red.startswith("Contact \u2588\u2588\u2588\u2588 at ")


def test_download_requires_permission_and_is_audited(org):
    inv = org.actor("investigator")
    researcher = org.actor("auditor")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    vid = ev["versions"][0]["id"]
    r = inv.get(f"/api/v1/evidence/{ev['id']}/versions/{vid}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["X-AEGIS-SHA256"] == ev["versions"][0]["sha256"]
    assert researcher.get(f"/api/v1/evidence/{ev['id']}/versions/{vid}/download").status_code == 403
    hist = inv.get(f"/api/v1/investigations/{case['id']}/history").json()
    assert any(h["action"] == "evidence.downloaded" for h in hist)


def test_chunked_upload(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    data = (fixtures.HUMAN_STYLE_SAMPLE * 3).encode()
    init = inv.post(
        f"/api/v1/investigations/{case['id']}/uploads", json={"filename": "chunked.txt", "total_size": len(data)}
    ).json()
    half = len(data) // 2
    assert inv.put(f"/api/v1/uploads/{init['upload_id']}", params={"offset": 0}, content=data[:half]).status_code == 200
    assert inv.put(f"/api/v1/uploads/{init['upload_id']}", params={"offset": 0}, content=data[half:]).status_code == 409
    assert (
        inv.put(f"/api/v1/uploads/{init['upload_id']}", params={"offset": half}, content=data[half:]).status_code == 200
    )
    r = inv.post(f"/api/v1/uploads/{init['upload_id']}/complete")
    assert r.status_code == 201
    import hashlib

    assert r.json()["versions"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_deletion_two_person_rule_and_legal_hold(org):
    inv = org.actor("investigator")
    rev = org.actor("independent_reviewer")
    admin = org.actor("org_admin")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    assert (
        admin.post(
            f"/api/v1/investigations/{case['id']}/legal-hold", json={"legal_hold": True, "reason": "Litigation hold"}
        ).status_code
        == 200
    )
    r = inv.post(f"/api/v1/investigations/{case['id']}/deletion-requests", json={"reason": "Retention period expired"})
    assert r.json()["status"] == "blocked"
    admin.post(f"/api/v1/investigations/{case['id']}/legal-hold", json={"legal_hold": False, "reason": "Hold lifted"})
    req = inv.post(
        f"/api/v1/investigations/{case['id']}/deletion-requests", json={"reason": "Retention period expired"}
    ).json()
    r = rev.post(
        f"/api/v1/investigations/{case['id']}/deletion-requests/{req['id']}/decide",
        json={"approve": True, "reason": "Approved under policy"},
    )
    assert r.status_code == 200 and r.json()["versions_purged"] == 2
    item = inv.get(f"/api/v1/evidence/{ev['id']}").json()
    assert item["status"] == "purged" and item["versions"][0]["sha256"]  # hash retained as tombstone
    vid = item["versions"][0]["id"]
    assert inv.get(f"/api/v1/evidence/{ev['id']}/versions/{vid}/download").status_code == 410


def test_requester_cannot_approve_own_deletion(org):
    rev = org.actor("independent_reviewer")
    inv = org.actor("investigator")
    case = new_case(inv)
    from app.db import get_sessionmaker
    from app.models import DeletionRequest

    with get_sessionmaker()() as db:
        dr = DeletionRequest(
            investigation_id=case["id"],
            requested_by_id=org.user_ids["independent_reviewer"],
            reason="self-approval attempt",
        )
        db.add(dr)
        db.commit()
        rid = dr.id
    r = rev.post(
        f"/api/v1/investigations/{case['id']}/deletion-requests/{rid}/decide",
        json={"approve": True, "reason": "trying"},
    )
    assert r.status_code == 403


def test_state_machine_rules(org):
    inv = org.actor("investigator")
    rev = org.actor("independent_reviewer")
    case = new_case(inv)
    assert (
        inv.post(f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review"}).status_code == 409
    )
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    run_job(inv, case["id"], ev["id"])
    r = inv.post(f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review"})
    assert r.status_code == 409  # reviewer must be assigned first
    assert (
        inv.post(
            f"/api/v1/investigations/{case['id']}/assign", json={"reviewer_id": str(org.user_ids["investigator"])}
        ).status_code
        == 400
    )
    assert (
        inv.post(
            f"/api/v1/investigations/{case['id']}/assign",
            json={"reviewer_id": str(org.user_ids["independent_reviewer"])},
        ).status_code
        == 200
    )
    assert (
        inv.post(f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review"}).status_code == 200
    )
    assert (
        inv.post(
            f"/api/v1/investigations/{case['id']}/reviews",
            json={"decision": "inconclusive", "rationale": "Creator attempting to review own case."},
        ).status_code
        == 403
    )
    r = rev.post(
        f"/api/v1/investigations/{case['id']}/reviews",
        json={
            "decision": "inconclusive",
            "rationale": "Only descriptive statistics were available; nothing interpretable.",
        },
    )
    assert r.status_code == 201
    assert inv.get(f"/api/v1/investigations/{case['id']}").json()["status"] == "inconclusive"
    rep = inv.post(f"/api/v1/investigations/{case['id']}/reports").json()
    rev.post(f"/api/v1/reports/{rep['id']}/finalize")
    assert (
        inv.post(
            f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review", "reason": "x"}
        ).status_code
        == 403
    )  # needs case.reopen
    r = rev.post(f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review", "reason": "short"})
    assert r.status_code == 422
    r = rev.post(
        f"/api/v1/investigations/{case['id']}/transition",
        json={"target": "human_review", "reason": "New process evidence was submitted by the author."},
    )
    assert r.status_code == 200


def test_appeal_workflow(org):
    inv = org.actor("investigator")
    rev = org.actor("independent_reviewer")
    case = new_case(inv)
    a = inv.post(
        f"/api/v1/investigations/{case['id']}/appeals",
        json={"grounds": "The author has supplied dated drafts showing the writing process."},
    )
    assert a.status_code == 201
    aid = a.json()["id"]
    assert (
        inv.post(
            f"/api/v1/investigations/{case['id']}/appeals/{aid}/resolve",
            json={"status": "upheld", "resolution": "self"},
        ).status_code
        == 403
    )
    r = rev.post(
        f"/api/v1/investigations/{case['id']}/appeals/{aid}/resolve",
        json={"status": "upheld", "resolution": "Drafts corroborate human authorship of the process."},
    )
    assert r.status_code == 200 and r.json()["status"] == "upheld"


def test_process_evidence_role(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    r = upload(inv, case["id"], "draft-v1.txt", fixtures.HUMAN_STYLE_SAMPLE.encode(), role="process_evidence")
    assert r.status_code == 201 and r.json()["role"] == "process_evidence"


def test_overview_counts_are_real(org):
    inv = org.actor("investigator")
    before = inv.get("/api/v1/overview").json()
    new_case(inv)
    after = inv.get("/api/v1/overview").json()
    assert after["investigations"]["total"] == before["investigations"]["total"] + 1
    assert after["source"] == "live database counts"


def test_idempotent_job_creation_and_resume(org):
    from app.services.analysis import execute_job

    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    body = {"evidence_item_id": ev["id"], "profile_id": "text_triage"}
    h = {"Idempotency-Key": f"idem-{case['id']}"}
    j1 = inv.post(f"/api/v1/analysis/investigations/{case['id']}/jobs", json=body, headers=h).json()
    j2 = inv.post(f"/api/v1/analysis/investigations/{case['id']}/jobs", json=body, headers=h).json()
    assert j1["id"] == j2["id"]
    assert execute_job(j1["id"]) == "completed"
    assert execute_job(j1["id"]) == "completed"  # re-delivery is a no-op
    runs = inv.get(f"/api/v1/analysis/jobs/{j1['id']}").json()["runs"]
    assert len(runs) == len({r["method_id"] for r in runs})


def test_cancel_queued_job(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    j = inv.post(
        f"/api/v1/analysis/investigations/{case['id']}/jobs",
        json={"evidence_item_id": ev["id"], "profile_id": "text_triage"},
    ).json()
    r = inv.post(f"/api/v1/analysis/jobs/{j['id']}/cancel").json()
    assert r["status"] == "cancelled" and all(x["status"] == "cancelled" for x in r["runs"])


def test_failed_method_is_not_negative(org, monkeypatch):
    """A crashing detector yields FAILED, the job reports failures, fusion lists it as failed."""
    from aegis_ml.text.features import DescriptiveTextStatistics

    def boom(self, inp):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(DescriptiveTextStatistics, "_run", boom)
    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    job = run_job(inv, case["id"], ev["id"])
    assert job["status"] == "completed_with_failures"
    run = next(r for r in job["runs"] if r["method_id"] == "text.descriptive_statistics")
    assert run["status"] == "failed" and run["flagged"] is None and "RuntimeError" in run["error"]
    assert any(f["method_id"] == "text.descriptive_statistics" for f in job["fusion"]["failed"])


def test_provider_failure_and_policy(org, monkeypatch):
    """External provider: blocked unless deployment+org+case allow it; HTTP errors become FAILED."""
    import httpx
    from app.core.config import get_settings
    from app.db import get_sessionmaker
    from app.models import Organization

    monkeypatch.setenv("AEGIS_PROVIDER_IMAGE_DETECTOR_URL", "https://provider.invalid/detect")
    monkeypatch.setattr(get_settings(), "allow_external_processing", True)
    with get_sessionmaker()() as db:
        db.get(Organization, org.id).allow_external_processing = True
        db.commit()

    def fake_post(*a, **k):
        return httpx.Response(503, json={"error": "down"})

    monkeypatch.setattr(httpx, "post", fake_post)
    inv = org.actor("investigator")
    admin = org.actor("org_admin")
    case = new_case(inv, media_category="image")
    assert (
        inv.patch(f"/api/v1/investigations/{case['id']}", json={"allow_external_processing": True}).status_code == 403
    )
    assert (
        admin.patch(f"/api/v1/investigations/{case['id']}", json={"allow_external_processing": True}).status_code == 200
    )
    import tempfile
    from pathlib import Path

    jpg = fixtures.make_jpeg(Path(tempfile.mkdtemp()) / "a.jpg")
    ev = upload(inv, case["id"], "a.jpg", jpg.read_bytes()).json()
    job = run_job(inv, case["id"], ev["id"], "image_investigation")
    run = next(r for r in job["runs"] if r["method_id"] == "provider.image_detector")
    assert run["status"] == "failed" and "503" in run["summary"] and run["score"] is None
