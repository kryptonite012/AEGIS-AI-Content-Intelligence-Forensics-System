"""End-to-end workflow: sign in, create case, upload text, run a real method, review, annotate,
report, verify report references, audit trail."""

from aegis_ml import fixtures
from aegis_ml.text.reference_watermark import generate_reference_text
from conftest import new_case, run_job, upload

KEY = b"test-only-reference-watermark-key-123"


def test_full_text_workflow(org):
    inv = org.actor("investigator")
    rev = org.actor("independent_reviewer")
    analyst = org.actor("forensic_analyst")
    me = inv.get("/api/v1/auth/me").json()
    assert me["role"] == "investigator" and "case.create" in me["permissions"]
    case = new_case(inv, reviewer_id=org.user_ids["independent_reviewer"])
    assert case["status"] == "draft"

    text = generate_reference_text(KEY, 200, seed=3).encode()
    r = upload(inv, case["id"], "statement.txt", text)
    assert r.status_code == 201, r.text
    ev = r.json()
    import hashlib

    assert ev["versions"][0]["sha256"] == hashlib.sha256(text).hexdigest()
    assert [v["kind"] for v in ev["versions"]] == ["original", "normalized_text"]
    assert inv.get(f"/api/v1/investigations/{case['id']}").json()["status"] == "evidence_acquired"

    job = run_job(inv, case["id"], ev["id"])
    assert job["status"] == "completed"
    runs = {r["method_id"]: r for r in job["runs"]}
    assert runs["watermark.aegis_reference_text"]["status"] == "completed"
    assert runs["watermark.aegis_reference_text"]["flagged"] is True
    assert runs["text.supervised_classifier"]["status"] == "unavailable"
    assert runs["text.supervised_classifier"]["score"] is None
    assert job["fusion"]["primary_outcome"] == "evidence_of_recognized_watermark"
    assert inv.get(f"/api/v1/investigations/{case['id']}").json()["status"] == "analysis_complete"
    # Persisted: a fresh read returns identical results.
    again = inv.get(f"/api/v1/analysis/jobs/{job['id']}").json()
    assert again["fusion"] == job["fusion"]

    r = analyst.post(
        f"/api/v1/investigations/{case['id']}/annotations",
        json={"body": "Watermark z-score is far above threshold.", "kind": "finding", "evidence_item_id": ev["id"]},
    )
    assert r.status_code == 201
    r = inv.post(f"/api/v1/investigations/{case['id']}/transition", json={"target": "human_review"})
    assert r.status_code == 200 and r.json()["status"] == "human_review"

    r = rev.post(
        f"/api/v1/investigations/{case['id']}/reviews",
        json={
            "decision": "evidence_of_recognized_watermark",
            "agrees_with_automated": True,
            "rationale": "The AEGIS reference watermark for this deployment key is present with exact p < 1e-20.",
        },
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert len(review["content_sha256"]) == 64 and review["audit_event_hash"]

    r = inv.post(f"/api/v1/investigations/{case['id']}/reports")
    assert r.status_code == 201, r.text
    rep = r.json()
    payload = inv.get(f"/api/v1/reports/{rep['id']}/json").json()["payload"]
    assert payload["evidence_inventory"][0]["versions"][0]["sha256"] == ev["versions"][0]["sha256"]
    methods = payload["automated_findings"][0]["methods"]
    assert {m["method_id"] for m in methods} >= {"watermark.aegis_reference_text", "text.descriptive_statistics"}
    assert all(m["method_version"] for m in methods)
    assert payload["human_assessment"]["review_decisions"][0]["decision"] == "evidence_of_recognized_watermark"
    assert payload["audit_references"]["event_count"] > 5
    pdf = inv.get(f"/api/v1/reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert hashlib.sha256(pdf.content).hexdigest() == rep["pdf_sha256"]
    v = inv.post(f"/api/v1/reports/{rep['id']}/verify").json()
    assert v["intact"] and v["pdf_reproducible_from_json"]

    # Separation of duties: the author cannot finalise; the reviewer can.
    assert inv.post(f"/api/v1/reports/{rep['id']}/finalize").status_code == 403
    r = rev.post(f"/api/v1/reports/{rep['id']}/finalize")
    assert r.status_code == 200 and r.json()["status"] == "final"
    case_now = inv.get(f"/api/v1/investigations/{case['id']}").json()
    assert case_now["status"] == "report_finalized"
    # Finalised: edits and new evidence are refused; correction creates a new version.
    assert inv.patch(f"/api/v1/investigations/{case['id']}", json={"title": "Changed"}).status_code == 409
    assert upload(inv, case["id"], "late.txt", b"x" * 400).status_code == 409
    r = inv.post(f"/api/v1/reports/{rep['id']}/corrections", json={"reason": "Typo in the reviewer rationale field."})
    assert r.status_code == 201 and r.json()["version"] == 2 and r.json()["supersedes_id"] == rep["id"]

    hist = inv.get(f"/api/v1/investigations/{case['id']}/history").json()
    actions = {h["action"] for h in hist}
    assert {
        "investigation.created",
        "evidence.acquired",
        "analysis.queued",
        "analysis.completed",
        "review.decision_recorded",
        "report.generated",
        "report.finalized",
    } <= actions
    aud = org.actor("auditor")
    chain = aud.post("/api/v1/audit/verify").json()
    assert chain["valid"] is True


def test_inconclusive_and_insufficient_input(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "short.txt", b"Too short to analyse.").json()
    assert ev["extraction"]["sufficient_for_detection"] is False
    job = run_job(inv, case["id"], ev["id"])
    runs = {r["method_id"]: r for r in job["runs"]}
    assert runs["watermark.aegis_reference_text"]["status"] == "insufficient_input"
    assert job["fusion"]["primary_outcome"] == "no_reliable_conclusion"

    ev2 = upload(inv, case["id"], "notes.txt", (fixtures.HUMAN_STYLE_SAMPLE * 2).encode()).json()
    job = run_job(inv, case["id"], ev2["id"])
    assert job["fusion"]["primary_outcome"] == "inconclusive"
    assert any("does not indicate human authorship" in x for x in job["fusion"]["uncertainty_reasons"])


def test_media_and_provenance_jobs(org, tmp_path):
    inv = org.actor("investigator")
    case = new_case(inv, media_category="image")
    signed = tmp_path / "signed.jpg"
    fixtures.make_c2pa_signed_jpeg(signed, tmp_path, source_type="digitalCapture")
    ev = upload(inv, case["id"], "signed.jpg", signed.read_bytes()).json()
    assert [v["kind"] for v in ev["versions"]] == ["original", "thumbnail"]
    job = run_job(inv, case["id"], ev["id"], "image_investigation")
    runs = {r["method_id"]: r for r in job["runs"]}
    assert runs["provenance.c2pa"]["output"]["state"] == "signature_valid_signer_untrusted"
    assert runs["image.frequency_spectrum"]["artifacts"]
    art = runs["image.frequency_spectrum"]["artifacts"][0]
    img = inv.get(f"/api/v1/artifacts/{art['id']}")
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert runs["provider.image_detector"]["status"] == "blocked_by_policy"
    assert job["fusion"]["primary_outcome"] == "provenance_record_verified"
    recs = inv.get("/api/v1/provenance/records").json()
    assert any(r["evidence_id"] == ev["id"] for r in recs)

    wav = tmp_path / "a.wav"
    fixtures.make_wav(wav)
    ev = upload(inv, case["id"], "a.wav", wav.read_bytes()).json()
    job = run_job(inv, case["id"], ev["id"], "synthetic_speech")
    runs = {r["method_id"]: r for r in job["runs"]}
    assert runs["audio.signal_analysis"]["status"] == "completed"
    assert runs["audio.synthetic_speech_model"]["status"] == "unavailable"

    mp4 = tmp_path / "a.mp4"
    fixtures.make_mp4(mp4)
    ev = upload(inv, case["id"], "a.mp4", mp4.read_bytes()).json()
    job = run_job(inv, case["id"], ev["id"], "deepfake_video")
    runs = {r["method_id"]: r for r in job["runs"]}
    assert runs["video.temporal_consistency"]["status"] == "completed"
    seg = inv.get(f"/api/v1/analysis/runs/{runs['video.temporal_consistency']['id']}/segments")
    assert seg.status_code == 200
