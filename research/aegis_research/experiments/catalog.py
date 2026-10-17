"""The nine reliability experiment categories.

Every experiment returns a dict with:
    id, title, kind ("analytical" | "simulation"), question, config, results, notes, labels

``kind`` is never "measurement": none of these experiments evaluates a deployed detector on real
content. Simulated results characterise the *reference* methods under synthetic conditions only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import numpy as np
from scipy import stats

from aegis_research import reliability as rel
from aegis_research import watermark as wm

SIM_LABEL = "SIMULATION — synthetic data; not real-world validation of any detector"
ANALYTIC_LABEL = "ANALYTICAL — closed-form calculation under the stated assumptions"

_KEY = b"aegis-research-simulation-key-not-secret"  # simulation only; never a deployment key


def _result(id_: str, title: str, kind: str, question: str, config: dict, results: Any, notes: list[str]) -> dict:
    return {
        "id": id_,
        "title": title,
        "kind": kind,
        "label": SIM_LABEL if kind == "simulation" else ANALYTIC_LABEL,
        "question": question,
        "config": config,
        "results": results,
        "notes": notes,
    }


# 1 -------------------------------------------------------------------------
def base_rate_sensitivity(tpr: float = 0.90, fpr: float = 0.05, prevalence: float = 0.05,
                          population: int = 10_000) -> dict:
    grid = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5]
    example = rel.predictive_values(tpr, fpr, prevalence, population)
    curves = {
        f"fpr={f:g}": rel.ppv_sensitivity(tpr, f, grid) for f in sorted({0.01, fpr, 0.10})
    }
    return _result(
        "exp1_base_rate", "Base-rate sensitivity of PPV", "analytical",
        "How does the share of flagged items that are truly AI-generated change with prevalence?",
        {"tpr": tpr, "fpr": fpr, "prevalence": prevalence, "population": population, "prevalence_grid": grid},
        {"illustrative_example": example.to_dict(), "curves": curves},
        [
            "Reproduces the research paper's illustrative configuration (90% sensitivity, 5% FPR, "
            "5% prevalence). This is an analytical example, not a measured performance claim for AEGIS.",
            f"Under these assumptions roughly {example.false_flags_per_true_flag:.2f} false flags occur per "
            "true flag, so a flag alone cannot establish AI generation.",
        ],
    )


# 2 -------------------------------------------------------------------------
def subgroup_error_concentration(groups: dict | None = None) -> dict:
    groups = groups or {
        "group_A (majority writers)": {"n_human": 9000, "fpr": 0.02, "source": "assumed"},
        "group_B (minority writers)": {"n_human": 1000, "fpr": 0.10, "source": "assumed"},
    }
    rows = rel.subgroup_false_positive_share(groups)
    return _result(
        "exp2_subgroup", "Subgroup false-positive concentration", "analytical",
        "If false-positive rates differ by group, where do false accusations land?",
        {"groups": groups},
        rows,
        [
            "Subgroup rates are illustrative assumptions, not measurements of any detector.",
            "A group making up a small share of the population can receive a disproportionate share of "
            "false flags when its FPR is higher.",
        ],
    )


# 3 -------------------------------------------------------------------------
def independent_corroboration(tpr1: float = 0.90, fpr1: float = 0.05, tpr2: float = 0.80, fpr2: float = 0.05,
                              prevalence: float = 0.05, correlations: tuple[float, ...] = (0.0, 0.3, 0.6, 0.9),
                              n_per_class: int = 200_000, seed: int = 7) -> dict:
    assumed = rel.combined_rates_assuming_independence(tpr1, fpr1, tpr2, fpr2, "and")
    rng = np.random.default_rng(seed)
    # Binormal latent scores with within-class correlation rho; thresholds set from marginals.
    t1, t2 = stats.norm.isf(fpr1), stats.norm.isf(fpr2)
    mu1, mu2 = t1 - stats.norm.isf(tpr1), t2 - stats.norm.isf(tpr2)
    rows = []
    for rho in correlations:
        cov = [[1, rho], [rho, 1]]
        neg = rng.multivariate_normal([0, 0], cov, n_per_class)
        pos = rng.multivariate_normal([mu1, mu2], cov, n_per_class)
        f_and = float(((neg[:, 0] >= t1) & (neg[:, 1] >= t2)).mean())
        t_and = float(((pos[:, 0] >= t1) & (pos[:, 1] >= t2)).mean())
        rows.append({
            "within_class_correlation": rho,
            "empirical_joint_tpr": t_and,
            "empirical_joint_fpr": f_and,
            "assumed_independent_fpr": assumed["fpr"],
            "fpr_underestimate_factor": (f_and / assumed["fpr"]) if assumed["fpr"] else None,
            "ppv_empirical": rel.ppv(t_and, f_and, prevalence),
            "ppv_assumed_independent": rel.ppv(float(assumed["tpr"]), float(assumed["fpr"]), prevalence),
        })
    return _result(
        "exp3_corroboration", "Independent corroboration", "simulation",
        "How much does requiring a second signal help, and what if signals are correlated?",
        {"tpr1": tpr1, "fpr1": fpr1, "tpr2": tpr2, "fpr2": fpr2, "prevalence": prevalence,
         "n_per_class": n_per_class, "seed": seed, "latent_model": "bivariate normal"},
        {"assumption_based": assumed, "simulated": rows},
        [
            "The product of rates is valid only under conditional independence given the true class.",
            "Detectors trained on similar data are often correlated; joint FPR then exceeds the product.",
            "Researchers can compare against empirical joint outcomes in the Benchmark Laboratory.",
        ],
    )


# 4 -------------------------------------------------------------------------
def auroc_vs_strict_fpr(n_pos: int = 2000, n_neg: int = 2000, seed: int = 11) -> dict:
    rng = np.random.default_rng(seed)
    detectors = {
        # Same-ish AUROC, different tail behaviour.
        "binormal_equal_variance": (rng.normal(1.8, 1.0, n_pos), rng.normal(0, 1.0, n_neg)),
        "binormal_heavy_negative_tail": (rng.normal(1.6, 0.6, n_pos), rng.standard_t(3, n_neg)),
    }
    rows = []
    for name, (pos, neg) in detectors.items():
        y = np.r_[np.ones(n_pos, int), np.zeros(n_neg, int)]
        s = np.r_[pos, neg]
        ops = [rel.tpr_at_fpr(y, s, f) for f in (0.01, 0.001)]
        rows.append({
            "detector": name,
            "auroc": rel.auroc(y, s),
            "operating_points": [asdict(o) for o in ops],
        })
    return _result(
        "exp4_auroc_strict_fpr", "AUROC versus sensitivity at strict FPR", "simulation",
        "Do detectors with similar AUROC behave similarly at low false-positive operating points?",
        {"n_pos": n_pos, "n_neg": n_neg, "seed": seed},
        rows,
        [
            "AUROC summarises the whole curve; screening uses only its low-FPR corner.",
            f"With {n_neg} negatives, FPR=0.1% is not estimable (requires >= "
            f"{rel.min_negatives_for_fpr(0.001)} negatives with zero false positives).",
        ],
    )


# 5 -------------------------------------------------------------------------
def watermark_length_entropy(lengths: tuple[int, ...] = (10, 25, 50, 100, 200),
                             zipf_exponents: tuple[float, ...] = (0.6, 1.0, 1.5, 2.5),
                             trials: int = 30, vocab_size: int = 1024, seed: int = 5) -> dict:
    cfg = wm.WatermarkConfig(vocab_size=vocab_size, gamma=0.25, delta=2.0)
    mark = wm.GreenListWatermark(_KEY, cfg)
    rng = np.random.default_rng(seed)
    rows = []
    for s in zipf_exponents:
        lm = wm.SyntheticLM(vocab_size, s, seed=seed)
        for n in lengths:
            det = fp = 0
            for _ in range(trials):
                det += mark.detect(wm.generate(lm, n, rng, mark, int(rng.integers(vocab_size)))).detected
                fp += mark.detect(wm.generate(lm, n, rng, None, int(rng.integers(vocab_size)))).detected
            rows.append({"zipf_exponent": s, "mean_entropy_nats": lm.mean_entropy(), "length": n,
                         "detection_rate": det / trials, "false_positive_rate": fp / trials, "trials": trials})
    return _result(
        "exp5_watermark_length_entropy", "Watermark detection vs length and entropy", "simulation",
        "How many tokens are needed to detect the reference watermark under different entropy regimes?",
        {**asdict(cfg), "z_threshold": 4.0, "trials": trials, "seed": seed,
         "generator": "SyntheticLM (toy Markov model)", "watermark": "AEGIS reference green-list scheme"},
        rows,
        [
            "Generator and watermark are synthetic; results characterise the reference scheme only.",
            "Low-entropy text leaves little room for the green-list bias, reducing detectability.",
            f"Below {wm.minimum_tokens_for_detection(0.25, 4.0)} scored tokens z>=4 is unreachable at gamma=0.25.",
        ],
    )


# 6 -------------------------------------------------------------------------
def watermark_robustness(fractions: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5), length: int = 200,
                         trials: int = 30, vocab_size: int = 1024, zipf_exponent: float = 1.0, seed: int = 9) -> dict:
    cfg = wm.WatermarkConfig(vocab_size=vocab_size)
    mark = wm.GreenListWatermark(_KEY, cfg)
    lm = wm.SyntheticLM(vocab_size, zipf_exponent, seed)
    rng = np.random.default_rng(seed)
    samples = [wm.generate(lm, length, rng, mark, int(rng.integers(vocab_size))) for _ in range(trials)]
    rows = []
    for f in fractions:
        dets = [mark.detect(wm.replace_tokens(t, f, vocab_size, rng)) for t in samples]
        rows.append({"replacement_fraction": f, "detection_rate": float(np.mean([d.detected for d in dets])),
                     "mean_z": float(np.mean([d.z_score for d in dets])), "trials": trials})
    return _result(
        "exp6_watermark_robustness", "Watermark robustness under token replacement", "simulation",
        "How quickly does detection degrade under controlled random token replacement?",
        {**asdict(cfg), "length": length, "trials": trials, "zipf_exponent": zipf_exponent, "seed": seed},
        rows,
        [
            "Measures the specific reference implementation under uniform random replacement only.",
            "Real paraphrasing is not uniform random replacement; no general robustness claim follows.",
        ],
    )


# 7 -------------------------------------------------------------------------
def threshold_selection(targets: tuple[float, ...] = (1e-2, 1e-3, 1e-4, 1e-6), lengths: tuple[int, ...] = (50, 200),
                        gamma: float = 0.25) -> dict:
    rows = []
    for alpha in targets:
        z_norm = float(stats.norm.isf(alpha))
        for n in lengths:
            # Exact: smallest green count k with P(X>=k) <= alpha under Binomial(n, gamma)
            k = next(k for k in range(n + 2) if k > n or stats.binom.sf(k - 1, n, gamma) <= alpha)
            exact_fpr = float(stats.binom.sf(k - 1, n, gamma)) if k <= n else 0.0
            rows.append({
                "target_fpr": alpha, "tokens": n, "z_threshold_normal": z_norm,
                "exact_min_green_count": k if k <= n else None,
                "exact_achieved_fpr": exact_fpr,
                "normal_threshold_true_fpr": wm.exact_false_positive_rate(n, gamma, z_norm),
            })
    return _result(
        "exp7_threshold_selection", "Threshold selection against FPR tolerance", "analytical",
        "Which threshold meets a target false-positive tolerance, exactly versus approximately?",
        {"targets": targets, "lengths": lengths, "gamma": gamma},
        rows,
        ["No universal threshold is recommended; tolerance depends on the consequences of a false flag."],
    )


# 8 -------------------------------------------------------------------------
def watermark_strength_distortion(deltas: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0), length: int = 100,
                                  trials: int = 30, vocab_size: int = 1024, zipf_exponent: float = 1.0,
                                  seed: int = 13) -> dict:
    lm = wm.SyntheticLM(vocab_size, zipf_exponent, seed)
    rng = np.random.default_rng(seed)
    rows = []
    for d in deltas:
        mark = wm.GreenListWatermark(_KEY, wm.WatermarkConfig(vocab_size=vocab_size, delta=d))
        rate = np.mean([mark.detect(wm.generate(lm, length, rng, mark, int(rng.integers(vocab_size)))).detected
                        for _ in range(trials)])
        rows.append({"delta": d, "detection_rate": float(rate), "trials": trials,
                     **wm.watermark_distortion(lm, mark, contexts=300, seed=seed)})
    return _result(
        "exp8_strength_distortion", "Watermark strength versus output distortion", "simulation",
        "How does increasing the bias delta trade detectability for distributional distortion?",
        {"length": length, "trials": trials, "vocab_size": vocab_size, "zipf_exponent": zipf_exponent, "seed": seed},
        rows,
        ["KL divergence is one mathematical distortion measure; a low value does not show that semantic "
         "quality is preserved."],
    )


# 9 -------------------------------------------------------------------------
def false_positive_calibration(lengths: tuple[int, ...] = (10, 16, 25, 50, 100, 200, 500, 1000),
                               z_thresholds: tuple[float, ...] = (2.0, 4.0), gamma: float = 0.25) -> dict:
    rows = []
    for z in z_thresholds:
        approx = float(stats.norm.sf(z))
        for n in lengths:
            exact = wm.exact_false_positive_rate(n, gamma, z)
            rows.append({"z_threshold": z, "tokens": n, "exact_fpr": exact, "normal_approx_fpr": approx,
                         "ratio_exact_to_approx": exact / approx if approx else None})
    return _result(
        "exp9_fpr_calibration", "Exact binomial FPR versus normal approximation", "analytical",
        "How accurate is the z-test's normal approximation for short texts?",
        {"lengths": lengths, "z_thresholds": z_thresholds, "gamma": gamma,
         "model": "i.i.d. Bernoulli(gamma) green indicators under H0"},
        rows,
        [
            "Assumes independent green indicators; repeated n-grams violate this and must be deduplicated.",
            "The approximation can misstate the FPR substantially for short sequences.",
        ],
    )


EXPERIMENTS: dict[str, Callable[..., dict]] = {
    "exp1_base_rate": base_rate_sensitivity,
    "exp2_subgroup": subgroup_error_concentration,
    "exp3_corroboration": independent_corroboration,
    "exp4_auroc_strict_fpr": auroc_vs_strict_fpr,
    "exp5_watermark_length_entropy": watermark_length_entropy,
    "exp6_watermark_robustness": watermark_robustness,
    "exp7_threshold_selection": threshold_selection,
    "exp8_strength_distortion": watermark_strength_distortion,
    "exp9_fpr_calibration": false_positive_calibration,
}
