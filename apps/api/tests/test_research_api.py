import json

import pytest


def test_ppv_calculator_matches_paper(org):
    r = org.actor("researcher").post(
        "/api/v1/evaluation/ppv", json={"prevalence": 0.05, "tpr": 0.9, "fpr": 0.05, "sample_size": 10000}
    )
    body = r.json()
    assert body["ppv"] == pytest.approx(0.4865, abs=1e-4)
    assert body["expected_false_positives"] == pytest.approx(475)
    assert body["sources"]["tpr"] == "assumed"
    assert len(body["sensitivity"]) == 10
    bad = org.actor("researcher").post("/api/v1/evaluation/ppv", json={"prevalence": 1.5, "tpr": 0.9, "fpr": 0.05})
    assert bad.status_code == 422


def test_experiments_are_labelled(org):
    a = org.actor("researcher")
    assert len(a.get("/api/v1/evaluation/experiments").json()) == 9
    r = a.post("/api/v1/evaluation/experiments/exp1_base_rate/runs", json={"config": {}}).json()
    assert r["kind"] == "analytical" and "ANALYTICAL" in r["label"]
    r = a.post(
        "/api/v1/evaluation/experiments/exp6_watermark_robustness/runs", json={"config": {"trials": 4, "length": 80}}
    ).json()
    assert r["kind"] == "simulation" and "SIMULATION" in r["label"]
    assert a.post("/api/v1/evaluation/experiments/exp1_base_rate/runs", json={"config": {"evil": 1}}).status_code == 400
    assert (
        a.post(
            "/api/v1/evaluation/experiments/exp6_watermark_robustness/runs", json={"config": {"trials": 100000}}
        ).status_code
        == 400
    )


def test_reference_watermark_benchmark_and_threshold_explorer(org):
    an = org.actor("forensic_analyst")
    run = an.post("/api/v1/benchmarks/reference-watermark").json()
    assert run["status"] == "completed", run.get("error")
    assert run["result_kind"] == "simulated"
    overall = run["metrics"]["overall"]
    assert overall["auroc"] > 0.9
    assert run["metrics"]["threshold_source"] == "validation_split"
    assert set(run["metrics"]["robustness"]) == {"token_replacement_20pct", "token_replacement_40pct"}
    assert run["manifest"]["dataset"]["synthetic"] is True
    ops = {o["target_fpr"]: o for o in overall["operating_points"]}
    assert ops[0.001]["estimable"] is False  # too few negatives for 0.1%
    te = an.post(
        "/api/v1/evaluation/threshold-explorer", json={"benchmark_run_id": run["id"], "deployment_prevalence": 0.05}
    ).json()
    assert te["rows"] and "deployment_ppv" in te["rows"][0]
    fair = an.get(f"/api/v1/evaluation/fairness/{run['id']}").json()
    assert fair["groups"] and fair["result_kind"] == "simulated"
    # Simulated runs cannot validate a detector or create a validated calibration profile.
    admin = org.actor("org_admin")
    prof = admin.post(
        f"/api/v1/benchmarks/runs/{run['id']}/calibration-profiles",
        json={"target_fpr": 0.05, "population": "Synthetic pseudo-word text only."},
    ).json()
    assert prof["validated"] is False
    reg = next(m for m in admin.get("/api/v1/models").json() if m["method_id"] == "watermark.aegis_reference_text")
    r = admin.patch(
        f"/api/v1/models/{reg['id']}",
        json={
            "validation_status": "validated",
            "validation_benchmark_run_id": run["id"],
            "reason": "Attempt to validate on simulated data",
        },
    )
    assert r.status_code == 400 and "locally measured" in r.json()["error"]["message"]
    r = admin.patch(
        f"/api/v1/models/{reg['id']}", json={"validation_status": "validated", "reason": "Attempt without evidence"}
    )
    assert r.status_code == 400


def test_dataset_registration_requires_documentation_and_detects_contamination(org):
    an = org.actor("forensic_analyst")
    rows = [
        {"id": "a", "text": "Same text in two splits.", "label": 0, "split": "train"},
        {"id": "b", "text": "same text in two  splits.", "label": 0, "split": "test"},
        {"id": "c", "text": "Different text.", "label": 1, "split": "test"},
    ]
    raw = "\n".join(json.dumps(r) for r in rows).encode()
    files = {"file": ("d.jsonl", raw)}
    missing = an.post(
        "/api/v1/benchmarks/datasets",
        files=files,
        data={"name": "d", "version": "1", "provenance": "", "license": "CC0", "consent_basis": "n/a"},
    )
    assert missing.status_code in (400, 422)
    r = an.post(
        "/api/v1/benchmarks/datasets",
        files={"file": ("d.jsonl", raw)},
        data={
            "name": f"d{id(org)}",
            "version": "1",
            "provenance": "Unit test rows",
            "license": "CC0-1.0",
            "consent_basis": "Synthetic, no personal data",
            "is_synthetic": "true",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["duplicate_report"]["cross_split_duplicates"] == 1


def test_imported_scores_require_citation_for_published(org):
    an = org.actor("forensic_analyst")
    csv = b"label,score,group\n1,0.9,a\n0,0.2,a\n1,0.7,b\n0,0.4,b\n"
    r = an.post(
        "/api/v1/benchmarks/imported-scores",
        files={"file": ("s.csv", csv)},
        data={"name": "paper", "result_kind": "published"},
    )
    assert r.status_code == 400
    r = an.post(
        "/api/v1/benchmarks/imported-scores",
        files={"file": ("s.csv", csv)},
        data={"name": "local", "result_kind": "locally_measured"},
    )
    assert r.status_code == 201 and r.json()["metrics"]["overall"]["auroc"] == 1.0


def test_health_and_detectors_report_truthfully(org):
    a = org.actor("system_admin")
    h = a.get("/api/v1/health/components").json()
    comps = {c["id"]: c for c in h["components"]}
    assert comps["database"]["status"] == "operational"
    assert comps["malware_scanner"]["status"] == "unknown"
    methods = {m["id"]: m for m in h["methods"]}
    assert methods["text.supervised_classifier"]["available"] is False
    assert methods["provenance.c2pa"]["available"] is True
    assert methods["watermark.synthid_text"]["implementation"] == "placeholder"
    assert org.actor("investigator").get("/api/v1/detectors").status_code == 200
    assert a.get("/api/v1/health/live").json()["status"] == "ok"
