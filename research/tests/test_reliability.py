import math

import numpy as np
import pytest

from aegis_research import reliability as rel


def test_ppv_matches_paper_example():
    # 90% sensitivity, 5% FPR, 5% prevalence -> 0.045 / (0.045 + 0.0475)
    assert rel.ppv(0.90, 0.05, 0.05) == pytest.approx(0.045 / 0.0925)
    assert rel.ppv(0.90, 0.05, 0.05) == pytest.approx(0.486486, abs=1e-6)


def test_ppv_edge_cases():
    assert rel.ppv(0.0, 0.0, 0.5) is None  # nothing is ever flagged
    assert rel.ppv(1.0, 0.0, 0.01) == 1.0
    assert rel.ppv(0.9, 0.05, 0.0) == 0.0
    with pytest.raises(ValueError):
        rel.ppv(1.2, 0.05, 0.1)
    with pytest.raises(ValueError):
        rel.ppv(0.9, float("nan"), 0.1)


def test_npv_and_expected_counts():
    r = rel.predictive_values(0.9, 0.05, 0.05, sample_size=10_000)
    assert r.expected_true_positives == pytest.approx(450)
    assert r.expected_false_positives == pytest.approx(475)
    assert r.expected_false_negatives == pytest.approx(50)
    assert r.expected_true_negatives == pytest.approx(9025)
    assert r.npv == pytest.approx(9025 / (9025 + 50))
    assert r.false_flags_per_true_flag == pytest.approx(475 / 450)
    assert r.sources["tpr"] == "assumed"


def test_sources_are_recorded():
    r = rel.predictive_values(0.9, 0.05, 0.05, sources={"tpr": rel.RateSource.MEASURED})
    assert r.sources == {"tpr": "measured", "fpr": "assumed", "prevalence": "assumed"}


def test_wilson_and_exact_intervals():
    w = rel.wilson_interval(50, 100)
    assert w.low == pytest.approx(0.4038, abs=1e-3) and w.high == pytest.approx(0.5962, abs=1e-3)
    cp = rel.clopper_pearson_interval(0, 10)
    assert cp.low == 0.0 and cp.high == pytest.approx(0.3085, abs=1e-3)
    cp = rel.clopper_pearson_interval(10, 10)
    assert cp.high == 1.0 and cp.low == pytest.approx(0.6915, abs=1e-3)
    with pytest.raises(ValueError):
        rel.wilson_interval(5, 3)


def test_min_negatives_rule_of_three():
    assert rel.min_negatives_for_fpr(0.01) == 299
    assert rel.min_negatives_for_fpr(0.001) == 2995
    with pytest.raises(ValueError):
        rel.min_negatives_for_fpr(0.0)


def test_confusion_and_metrics():
    cm = rel.ConfusionMatrix.from_predictions([1, 1, 0, 0, 1, 0], [1, 0, 0, 1, 1, 0])
    assert (cm.tp, cm.fp, cm.tn, cm.fn) == (2, 1, 2, 1)
    m = rel.classification_metrics(cm)
    assert m.tpr.value == pytest.approx(2 / 3)
    assert m.fpr.value == pytest.approx(1 / 3)
    assert m.f1 == pytest.approx(2 / 3)
    assert any("Small evaluation sample" in w for w in m.warnings)


def test_auroc():
    assert rel.auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert rel.auroc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert rel.auroc([0, 1], [0.5, 0.5]) == 0.5
    assert rel.auroc([1, 1], [0.1, 0.2]) is None
    rng = np.random.default_rng(0)
    y = np.r_[np.ones(500, int), np.zeros(500, int)]
    s = np.r_[rng.normal(1, 1, 500), rng.normal(0, 1, 500)]
    # Binormal equal variance with d'=1: AUROC = Phi(1/sqrt 2) ~ 0.760
    assert rel.auroc(y, s) == pytest.approx(0.760, abs=0.03)
    ci = rel.auroc_bootstrap_ci(y, s, n_boot=200)
    assert ci.low < rel.auroc(y, s) < ci.high


def test_tpr_at_fpr_and_estimability():
    y = [0] * 100 + [1] * 100
    s = list(range(100)) + [x + 50 for x in range(100)]
    op = rel.tpr_at_fpr(y, s, 0.01)
    assert op.achieved_fpr <= 0.01
    assert op.estimable is False  # only 100 negatives < 299
    assert "not validated" in op.note


def test_roc_and_threshold_sweep():
    y, s = [0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]
    roc = rel.roc_curve(y, s)
    assert roc[0]["tpr"] == 0 and roc[-1]["tpr"] == 1 and roc[-1]["fpr"] == 1
    rows = rel.threshold_sweep(y, s, [0.3, 0.5], deployment_prevalence=0.05, population_size=1000)
    assert rows[1]["tp"] == 1 and rows[1]["fp"] == 0
    assert rows[1]["deployment_ppv"] == 1.0


def test_calibration_metrics():
    y = [0, 0, 1, 1]
    p = [0.0, 0.0, 1.0, 1.0]
    assert rel.brier_score(y, p) == 0.0
    assert rel.expected_calibration_error(y, p) == 0.0
    assert rel.brier_score([1], [0.0]) == 1.0
    with pytest.raises(ValueError):
        rel.brier_score([1], [1.5])


def test_platt_calibration_improves_log_loss():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 2000)
    s = rng.normal(y * 2.0, 1.0)
    cal = rel.PlattCalibrator.fit(y, s)
    p = cal.predict(s)
    assert cal.a > 0
    assert rel.expected_calibration_error(y, p) < 0.05


def test_independence_vs_empirical_joint():
    a = rel.combined_rates_assuming_independence(0.9, 0.05, 0.8, 0.05)
    assert a["tpr"] == pytest.approx(0.72) and a["fpr"] == pytest.approx(0.0025)
    e = rel.empirical_joint_rates([0, 0, 1, 1], [1, 0, 1, 1], [1, 0, 0, 1])
    assert e["fpr"] == 0.5 and e["tpr"] == 0.5


def test_subgroup_share_and_suppression():
    rows = rel.subgroup_false_positive_share(
        {"a": {"n_human": 900, "fpr": 0.02}, "b": {"n_human": 100, "fpr": 0.10}}
    )
    by = {r["group"]: r for r in rows}
    assert by["b"]["false_flag_share"] == pytest.approx(10 / 28)
    rows = rel.subgroup_false_positive_share({"a": {"n_human": 5, "fpr": 0.1}}, suppress_below=10)
    assert rows[0]["suppressed"] and rows[0]["expected_false_flags"] is None
    out = rel.subgroup_metrics([0] * 12 + [1] * 3, [0] * 15, ["x"] * 12 + ["y"] * 3, min_group_size=10)
    assert out[1] == {"group": "y", "n": None, "suppressed": True}


def test_evaluate_scores_bundle():
    rng = np.random.default_rng(3)
    y = np.r_[np.ones(200, int), np.zeros(200, int)]
    s = np.r_[rng.uniform(0.4, 1, 200), rng.uniform(0, 0.6, 200)]
    out = rel.evaluate_scores(y, s, 0.5, groups=["g"] * 400, probabilities_are_calibrated=True)
    assert out["n"] == 400 and 0.8 < out["auroc"] <= 1
    assert out["calibration"]["brier"] >= 0
    assert all(not math.isnan(p["tpr"]) for p in out["roc"])
