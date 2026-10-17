import numpy as np
import pytest
from aegis_research import watermark as wm
from aegis_research.experiments import EXPERIMENTS
from scipy import stats

KEY = b"test-key-0123456789abcdef"


def test_key_requirements_and_fingerprint():
    with pytest.raises(ValueError):
        wm.GreenListWatermark(b"short")
    a = wm.GreenListWatermark(KEY)
    assert len(a.key_fingerprint) == 16 and KEY.hex() not in a.key_fingerprint


def test_green_fraction_matches_gamma():
    m = wm.GreenListWatermark(KEY, wm.WatermarkConfig(vocab_size=1000, gamma=0.25))
    assert m.green_mask([3]).sum() == 250
    assert not np.array_equal(m.green_mask([3]), m.green_mask([4]))


def test_detects_watermarked_not_plain():
    cfg = wm.WatermarkConfig(vocab_size=512)
    m = wm.GreenListWatermark(KEY, cfg)
    lm = wm.SyntheticLM(512, 0.8, seed=1)
    rng = np.random.default_rng(0)
    marked = wm.generate(lm, 200, rng, m)
    plain = wm.generate(lm, 200, rng, None)
    assert m.detect(marked).detected
    d = m.detect(plain)
    assert not d.detected and d.z_score < 4
    other = wm.GreenListWatermark(b"another-key-0123456789", cfg)
    assert not other.detect(marked).detected  # wrong key does not verify


def test_short_input_is_insufficient():
    m = wm.GreenListWatermark(KEY)
    d = m.detect([1])
    assert d.z_score is None and not d.sufficient_length and not d.detected
    assert wm.minimum_tokens_for_detection(0.25, 4.0) == 6
    assert not m.detect([1, 2, 3]).sufficient_length


def test_exact_fpr_and_pvalues_consistent():
    d = wm.WatermarkDetection.from_counts(green=40, scored=100, gamma=0.25, z_threshold=4)
    assert d.p_value_exact == pytest.approx(stats.binom.sf(39, 100, 0.25))
    assert d.z_score == pytest.approx((40 - 25) / np.sqrt(100 * 0.25 * 0.75))
    assert 0 < wm.exact_false_positive_rate(200, 0.25, 4.0) < 1e-3


def test_replace_tokens_fraction():
    rng = np.random.default_rng(0)
    toks = list(range(101))
    out = wm.replace_tokens(toks, 0.0, 512, rng)
    assert out == toks
    with pytest.raises(ValueError):
        wm.replace_tokens(toks, 1.5, 512, rng)


def test_paper_example_in_experiment_1():
    r = EXPERIMENTS["exp1_base_rate"]()
    assert r["kind"] == "analytical"
    assert r["results"]["illustrative_example"]["ppv"] == pytest.approx(0.4865, abs=1e-4)


@pytest.mark.parametrize("exp_id", ["exp2_subgroup", "exp7_threshold_selection", "exp9_fpr_calibration"])
def test_analytical_experiments_run(exp_id):
    r = EXPERIMENTS[exp_id]()
    assert r["kind"] == "analytical" and r["results"]


def test_simulation_experiments_are_labeled():
    r = EXPERIMENTS["exp6_watermark_robustness"](trials=5, length=120, fractions=(0.0, 0.5))
    assert r["kind"] == "simulation" and "SIMULATION" in r["label"]
    assert r["results"][0]["detection_rate"] >= r["results"][1]["detection_rate"]
    r = EXPERIMENTS["exp3_corroboration"](n_per_class=20_000, correlations=(0.0, 0.9))
    sim = r["results"]["simulated"]
    assert sim[1]["empirical_joint_fpr"] > sim[0]["empirical_joint_fpr"]
