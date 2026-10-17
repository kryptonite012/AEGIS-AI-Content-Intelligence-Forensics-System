"""Statistical reliability engine.

Implements the quantities needed to judge whether a detector flag can be trusted in a given
deployment: confusion-matrix rates with exact and Wilson intervals, Bayes'-rule PPV/NPV under
stated prevalence, ROC/PR curves, AUROC, calibration (Brier, ECE, reliability bins), sensitivity
at fixed false-positive operating points with sample-size adequacy checks, and threshold sweeps.

Conventions
-----------
* Label 1 = AI-generated (positive class), label 0 = human-written (negative class).
* Scores are "higher = more consistent with AI generation". Scores are NOT probabilities unless a
  calibration profile validated on held-out data says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum

import numpy as np
from scipy import stats


class RateSource(StrEnum):
    """Where an input rate came from. Displayed next to every derived number."""

    MEASURED = "measured"  # estimated from labeled evaluation data recorded in AEGIS
    ASSUMED = "assumed"  # entered by a researcher as an assumption
    PUBLISHED = "published"  # copied from a cited publication (not reproduced)
    VENDOR_REPORTED = "vendor_reported"  # claimed by a provider, not independently verified
    SIMULATED = "simulated"  # produced by a synthetic simulation


@dataclass(frozen=True)
class Interval:
    low: float
    high: float
    method: str
    confidence: float = 0.95


def _check_rate(name: str, value: float) -> None:
    if not (0.0 <= value <= 1.0) or math.isnan(value):
        raise ValueError(f"{name} must be within [0, 1], got {value!r}")


# ---------------------------------------------------------------------------
# Binomial confidence intervals
# ---------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> Interval:
    """Wilson score interval for a binomial proportion."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("require 0 <= successes <= n")
    if n == 0:
        return Interval(0.0, 1.0, "wilson", confidence)
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return Interval(max(0.0, centre - half), min(1.0, centre + half), "wilson", confidence)


def clopper_pearson_interval(successes: int, n: int, confidence: float = 0.95) -> Interval:
    """Exact (Clopper-Pearson) binomial interval. Conservative; preferred for rare events."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("require 0 <= successes <= n")
    if n == 0:
        return Interval(0.0, 1.0, "clopper_pearson", confidence)
    alpha = 1 - confidence
    low = 0.0 if successes == 0 else float(stats.beta.ppf(alpha / 2, successes, n - successes + 1))
    high = 1.0 if successes == n else float(stats.beta.ppf(1 - alpha / 2, successes + 1, n - successes))
    return Interval(low, high, "clopper_pearson", confidence)


def min_negatives_for_fpr(target_fpr: float, confidence: float = 0.95) -> int:
    """Smallest number of negatives such that observing ZERO false positives bounds the FPR
    below ``target_fpr`` at the given one-sided confidence (exact binomial; ~ 3/FPR at 95%)."""
    _check_rate("target_fpr", target_fpr)
    if target_fpr == 0:
        raise ValueError("an FPR of exactly zero can never be established from finite samples")
    return math.ceil(math.log(1 - confidence) / math.log(1 - target_fpr))


# ---------------------------------------------------------------------------
# Confusion matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def positives(self) -> int:
        return self.tp + self.fn

    @property
    def negatives(self) -> int:
        return self.tn + self.fp

    @property
    def n(self) -> int:
        return self.positives + self.negatives

    @staticmethod
    def from_predictions(labels: Sequence[int], predictions: Sequence[int]) -> ConfusionMatrix:
        y = np.asarray(labels, dtype=int)
        p = np.asarray(predictions, dtype=int)
        if y.shape != p.shape:
            raise ValueError("labels and predictions must have equal length")
        if not set(np.unique(y)).issubset({0, 1}) or not set(np.unique(p)).issubset({0, 1}):
            raise ValueError("labels and predictions must be 0/1")
        return ConfusionMatrix(
            tp=int(((y == 1) & (p == 1)).sum()),
            fp=int(((y == 0) & (p == 1)).sum()),
            tn=int(((y == 0) & (p == 0)).sum()),
            fn=int(((y == 1) & (p == 0)).sum()),
        )


def _safe_div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


@dataclass
class RateEstimate:
    value: float | None
    numerator: int
    denominator: int
    interval: Interval | None


def _rate(num: int, den: int, confidence: float) -> RateEstimate:
    value = _safe_div(num, den)
    interval = clopper_pearson_interval(num, den, confidence) if den > 0 else None
    return RateEstimate(value, num, den, interval)


@dataclass
class ClassificationMetrics:
    confusion: ConfusionMatrix
    tpr: RateEstimate
    tnr: RateEstimate
    fpr: RateEstimate
    fnr: RateEstimate
    precision: RateEstimate
    npv: RateEstimate
    accuracy: RateEstimate
    f1: float | None
    sample_prevalence: float | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def classification_metrics(cm: ConfusionMatrix, confidence: float = 0.95) -> ClassificationMetrics:
    """Rates with exact intervals. Precision/NPV here use the *sample* prevalence, which is
    rarely the deployment prevalence; use :func:`predictive_values` for deployment PPV."""
    warnings: list[str] = []
    precision = _rate(cm.tp, cm.tp + cm.fp, confidence)
    tpr = _rate(cm.tp, cm.positives, confidence)
    f1 = None
    if precision.value is not None and tpr.value is not None and (precision.value + tpr.value) > 0:
        f1 = 2 * precision.value * tpr.value / (precision.value + tpr.value)
    if cm.positives < 30 or cm.negatives < 30:
        warnings.append(
            f"Small evaluation sample (positives={cm.positives}, negatives={cm.negatives}); "
            "intervals are wide and point estimates are unstable."
        )
    warnings.append(
        "Precision/NPV reflect the evaluation sample's class balance, not a deployment population."
    )
    return ClassificationMetrics(
        confusion=cm,
        tpr=tpr,
        tnr=_rate(cm.tn, cm.negatives, confidence),
        fpr=_rate(cm.fp, cm.negatives, confidence),
        fnr=_rate(cm.fn, cm.positives, confidence),
        precision=precision,
        npv=_rate(cm.tn, cm.tn + cm.fn, confidence),
        accuracy=_rate(cm.tp + cm.tn, cm.n, confidence),
        f1=f1,
        sample_prevalence=_safe_div(cm.positives, cm.n),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Bayes' rule: deployment predictive values
# ---------------------------------------------------------------------------


@dataclass
class PredictiveValueResult:
    ppv: float | None
    npv: float | None
    prevalence: float
    tpr: float
    fpr: float
    sample_size: int | None
    expected_true_positives: float | None
    expected_false_positives: float | None
    expected_false_negatives: float | None
    expected_true_negatives: float | None
    expected_flags: float | None
    false_flags_per_true_flag: float | None
    sources: dict[str, str]
    assumptions: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def ppv(tpr: float, fpr: float, prevalence: float) -> float | None:
    """PPV = TPR*pi / (TPR*pi + FPR*(1-pi)). Returns None when no item would ever be flagged."""
    for name, v in (("tpr", tpr), ("fpr", fpr), ("prevalence", prevalence)):
        _check_rate(name, v)
    num = tpr * prevalence
    den = num + fpr * (1 - prevalence)
    return None if den == 0 else num / den


def npv(tpr: float, fpr: float, prevalence: float) -> float | None:
    """NPV = (1-FPR)(1-pi) / ((1-FPR)(1-pi) + (1-TPR)pi)."""
    for name, v in (("tpr", tpr), ("fpr", fpr), ("prevalence", prevalence)):
        _check_rate(name, v)
    num = (1 - fpr) * (1 - prevalence)
    den = num + (1 - tpr) * prevalence
    return None if den == 0 else num / den


def predictive_values(
    tpr: float,
    fpr: float,
    prevalence: float,
    sample_size: int | None = None,
    sources: dict[str, str] | None = None,
) -> PredictiveValueResult:
    """Bayes'-rule predictive values plus expected counts for a screening population."""
    p = ppv(tpr, fpr, prevalence)
    q = npv(tpr, fpr, prevalence)
    srcs = {"tpr": RateSource.ASSUMED, "fpr": RateSource.ASSUMED, "prevalence": RateSource.ASSUMED}
    srcs.update(sources or {})
    counts: dict[str, float | None] = dict.fromkeys(("tp", "fp", "fn", "tn"))
    flags = ratio = None
    if sample_size is not None:
        if sample_size < 0:
            raise ValueError("sample_size must be non-negative")
        ai = sample_size * prevalence
        human = sample_size - ai
        counts = {"tp": ai * tpr, "fn": ai * (1 - tpr), "fp": human * fpr, "tn": human * (1 - fpr)}
        flags = counts["tp"] + counts["fp"]
        ratio = None if counts["tp"] == 0 else counts["fp"] / counts["tp"]
    return PredictiveValueResult(
        ppv=p,
        npv=q,
        prevalence=prevalence,
        tpr=tpr,
        fpr=fpr,
        sample_size=sample_size,
        expected_true_positives=counts["tp"],
        expected_false_positives=counts["fp"],
        expected_false_negatives=counts["fn"],
        expected_true_negatives=counts["tn"],
        expected_flags=flags,
        false_flags_per_true_flag=ratio,
        sources={k: str(v) for k, v in srcs.items()},
        assumptions=[
            "TPR and FPR are assumed to hold in the deployment population (no distribution shift).",
            "Prevalence is the proportion of AI-generated items in the population actually screened.",
            "PPV is a population-level expectation, not the probability for any specific item "
            "unless the detector's operating characteristics are valid for that item's subgroup.",
        ],
    )


def ppv_sensitivity(
    tpr: float, fpr: float, prevalences: Sequence[float]
) -> list[dict[str, float | None]]:
    return [{"prevalence": pi, "ppv": ppv(tpr, fpr, pi), "npv": npv(tpr, fpr, pi)} for pi in prevalences]


# ---------------------------------------------------------------------------
# Score-based metrics
# ---------------------------------------------------------------------------


def _validate_scores(labels: Sequence[int], scores: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=int)
    s = np.asarray(scores, dtype=float)
    if y.ndim != 1 or y.shape != s.shape:
        raise ValueError("labels and scores must be 1-D arrays of equal length")
    if not set(np.unique(y)).issubset({0, 1}):
        raise ValueError("labels must be 0/1")
    if np.isnan(s).any():
        raise ValueError("scores must not contain NaN")
    return y, s


def auroc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """AUROC via the Mann-Whitney U statistic (ties count one half)."""
    y, s = _validate_scores(labels, scores)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = stats.rankdata(s)
    u = ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2
    return float(u / (n_pos * n_neg))


def auroc_bootstrap_ci(
    labels: Sequence[int], scores: Sequence[float], n_boot: int = 1000, seed: int = 0, confidence: float = 0.95
) -> Interval | None:
    y, s = _validate_scores(labels, scores)
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    vals = []
    for _ in range(n_boot):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        v = auroc(y[idx], s[idx])
        if v is not None:
            vals.append(v)
    a = (1 - confidence) / 2
    return Interval(float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a)), "stratified_bootstrap", confidence)


def roc_curve(labels: Sequence[int], scores: Sequence[float]) -> list[dict[str, float]]:
    """ROC points for thresholds "flag if score >= t", from strictest to most lenient."""
    y, s = _validate_scores(labels, scores)
    n_pos, n_neg = (y == 1).sum(), (y == 0).sum()
    points = [{"threshold": math.inf, "fpr": 0.0, "tpr": 0.0}]
    for t in np.unique(s)[::-1]:
        flagged = s >= t
        points.append(
            {
                "threshold": float(t),
                "fpr": float((flagged & (y == 0)).sum() / n_neg) if n_neg else 0.0,
                "tpr": float((flagged & (y == 1)).sum() / n_pos) if n_pos else 0.0,
            }
        )
    return points


def pr_curve(labels: Sequence[int], scores: Sequence[float]) -> list[dict[str, float]]:
    y, s = _validate_scores(labels, scores)
    n_pos = (y == 1).sum()
    points = []
    for t in np.unique(s)[::-1]:
        flagged = s >= t
        tp = (flagged & (y == 1)).sum()
        fp = (flagged & (y == 0)).sum()
        points.append(
            {
                "threshold": float(t),
                "recall": float(tp / n_pos) if n_pos else 0.0,
                "precision": float(tp / (tp + fp)) if (tp + fp) else 1.0,
            }
        )
    return points


@dataclass
class OperatingPoint:
    target_fpr: float
    threshold: float | None
    achieved_fpr: float | None
    tpr: RateEstimate | None
    fpr_interval: Interval | None
    negatives: int
    min_negatives_required: int
    estimable: bool
    note: str


def tpr_at_fpr(
    labels: Sequence[int], scores: Sequence[float], target_fpr: float, confidence: float = 0.95
) -> OperatingPoint:
    """Sensitivity at the most lenient threshold whose empirical FPR <= target.

    ``estimable`` is False when the number of negatives is too small for the target FPR to be
    distinguishable from zero false positives (exact binomial bound); in that case AEGIS reports
    the number but must not present it as a validated operating point.
    """
    _check_rate("target_fpr", target_fpr)
    y, s = _validate_scores(labels, scores)
    n_neg = int((y == 0).sum())
    n_pos = int((y == 1).sum())
    required = min_negatives_for_fpr(target_fpr, confidence) if target_fpr > 0 else 0
    estimable = n_neg >= required and n_pos > 0
    best: tuple[float, int, int] | None = None
    for t in np.unique(s)[::-1]:
        flagged = s >= t
        fp = int((flagged & (y == 0)).sum())
        if n_neg and fp / n_neg <= target_fpr:
            tp = int((flagged & (y == 1)).sum())
            best = (float(t), fp, tp)
        else:
            break
    if best is None:
        return OperatingPoint(
            target_fpr, None, None, None, None, n_neg, required, estimable,
            "No threshold achieves the target false-positive rate on this sample.",
        )
    t, fp, tp = best
    note = (
        "Operating point estimable from this sample."
        if estimable
        else f"Only {n_neg} negatives; at least {required} are needed to bound FPR at {target_fpr:g} "
        "with zero observed false positives. Treat this operating point as not validated."
    )
    return OperatingPoint(
        target_fpr=target_fpr,
        threshold=t,
        achieved_fpr=fp / n_neg,
        tpr=_rate(tp, n_pos, confidence),
        fpr_interval=clopper_pearson_interval(fp, n_neg, confidence),
        negatives=n_neg,
        min_negatives_required=required,
        estimable=estimable,
        note=note,
    )


def threshold_sweep(
    labels: Sequence[int],
    scores: Sequence[float],
    thresholds: Sequence[float] | None = None,
    deployment_prevalence: float | None = None,
    population_size: int | None = None,
) -> list[dict[str, float | None]]:
    """Trade-offs per threshold, optionally projected to a deployment population."""
    y, s = _validate_scores(labels, scores)
    if thresholds is None:
        thresholds = np.unique(np.quantile(s, np.linspace(0, 1, 41)))
    rows = []
    for t in thresholds:
        cm = ConfusionMatrix.from_predictions(y, (s >= t).astype(int))
        tpr_v = _safe_div(cm.tp, cm.positives)
        fpr_v = _safe_div(cm.fp, cm.negatives)
        row: dict[str, float | None] = {
            "threshold": float(t),
            "tpr": tpr_v,
            "fpr": fpr_v,
            "sample_precision": _safe_div(cm.tp, cm.tp + cm.fp),
            "tp": cm.tp, "fp": cm.fp, "tn": cm.tn, "fn": cm.fn,
        }
        if deployment_prevalence is not None and tpr_v is not None and fpr_v is not None:
            pv = predictive_values(tpr_v, fpr_v, deployment_prevalence, population_size)
            row.update(
                {
                    "deployment_ppv": pv.ppv,
                    "expected_review_volume": pv.expected_flags,
                    "expected_false_flags": pv.expected_false_positives,
                    "expected_missed_ai": pv.expected_false_negatives,
                }
            )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def brier_score(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    y, p = _validate_scores(labels, probabilities)
    if ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must lie in [0, 1]")
    return float(np.mean((p - y) ** 2))


def reliability_bins(
    labels: Sequence[int], probabilities: Sequence[float], n_bins: int = 10
) -> list[dict[str, float | int | None]]:
    y, p = _validate_scores(labels, probabilities)
    if ((p < 0) | (p > 1)).any():
        raise ValueError("probabilities must lie in [0, 1]")
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
    bins = []
    for b in range(n_bins):
        m = idx == b
        count = int(m.sum())
        bins.append(
            {
                "bin_low": float(edges[b]),
                "bin_high": float(edges[b + 1]),
                "count": count,
                "mean_predicted": float(p[m].mean()) if count else None,
                "observed_frequency": float(y[m].mean()) if count else None,
            }
        )
    return bins


def expected_calibration_error(labels: Sequence[int], probabilities: Sequence[float], n_bins: int = 10) -> float:
    bins = reliability_bins(labels, probabilities, n_bins)
    n = len(labels)
    return float(
        sum(
            b["count"] / n * abs(b["mean_predicted"] - b["observed_frequency"])  # type: ignore[operator]
            for b in bins
            if b["count"]
        )
    )


@dataclass
class PlattCalibrator:
    """Logistic (Platt) calibration fitted on held-out data. Only meaningful for the population
    it was fitted on; AEGIS stores the fitting dataset reference with every profile."""

    a: float
    b: float

    @staticmethod
    def fit(labels: Sequence[int], scores: Sequence[float], max_iter: int = 200) -> PlattCalibrator:
        y, s = _validate_scores(labels, scores)
        if len(np.unique(y)) < 2:
            raise ValueError("calibration requires both classes")
        # Platt's target smoothing to avoid overconfident fits.
        n_pos, n_neg = (y == 1).sum(), (y == 0).sum()
        t = np.where(y == 1, (n_pos + 1) / (n_pos + 2), 1 / (n_neg + 2))
        a, b = 0.0, 0.0
        for _ in range(max_iter):  # Newton-Raphson on the log-loss
            z = a * s + b
            p = 1 / (1 + np.exp(-z))
            g = np.array([np.sum((p - t) * s), np.sum(p - t)])
            w = p * (1 - p) + 1e-12
            h = np.array([[np.sum(w * s * s), np.sum(w * s)], [np.sum(w * s), np.sum(w)]])
            step = np.linalg.solve(h + 1e-9 * np.eye(2), g)
            a, b = a - step[0], b - step[1]
            if np.abs(step).max() < 1e-10:
                break
        return PlattCalibrator(float(a), float(b))

    def predict(self, scores: Sequence[float]) -> np.ndarray:
        s = np.asarray(scores, dtype=float)
        return 1 / (1 + np.exp(-(self.a * s + self.b)))


# ---------------------------------------------------------------------------
# Corroboration and subgroup analysis
# ---------------------------------------------------------------------------


def combined_rates_assuming_independence(
    tpr1: float, fpr1: float, tpr2: float, fpr2: float, rule: str = "and"
) -> dict[str, float | str]:
    """Rates for a two-signal rule *if* signals are conditionally independent given the class.
    The assumption is returned with the result; it is rarely guaranteed for detectors trained on
    similar data."""
    for name, v in (("tpr1", tpr1), ("fpr1", fpr1), ("tpr2", tpr2), ("fpr2", fpr2)):
        _check_rate(name, v)
    if rule == "and":
        tpr, fpr = tpr1 * tpr2, fpr1 * fpr2
    elif rule == "or":
        tpr, fpr = 1 - (1 - tpr1) * (1 - tpr2), 1 - (1 - fpr1) * (1 - fpr2)
    else:
        raise ValueError("rule must be 'and' or 'or'")
    return {
        "tpr": tpr,
        "fpr": fpr,
        "rule": rule,
        "assumption": "conditional independence of the two signals given the true class",
    }


def empirical_joint_rates(
    labels: Sequence[int], flags1: Sequence[int], flags2: Sequence[int], rule: str = "and"
) -> dict[str, float | int | None]:
    y = np.asarray(labels, dtype=int)
    a = np.asarray(flags1, dtype=int)
    b = np.asarray(flags2, dtype=int)
    joint = (a & b) if rule == "and" else (a | b)
    cm = ConfusionMatrix.from_predictions(y, joint)
    return {
        "tpr": _safe_div(cm.tp, cm.positives),
        "fpr": _safe_div(cm.fp, cm.negatives),
        "positives": cm.positives,
        "negatives": cm.negatives,
        "rule": rule,
    }


def subgroup_false_positive_share(
    groups: dict[str, dict[str, float]], suppress_below: int = 0
) -> list[dict[str, float | str | bool | None]]:
    """Given per-group human population size and FPR, compute where false flags land.

    ``groups`` maps name -> {"n_human": int, "fpr": float, "source": str}.
    Groups with fewer than ``suppress_below`` members are suppressed (counts withheld).
    """
    expected = {g: v["n_human"] * v["fpr"] for g, v in groups.items()}
    total = sum(expected.values())
    total_humans = sum(v["n_human"] for v in groups.values())
    rows: list[dict[str, float | str | bool | None]] = []
    for g, v in groups.items():
        _check_rate(f"fpr[{g}]", v["fpr"])
        suppressed = v["n_human"] < suppress_below
        rows.append(
            {
                "group": g,
                "fpr": v["fpr"],
                "source": str(v.get("source", RateSource.ASSUMED)),
                "population_share": None if suppressed else v["n_human"] / total_humans,
                "expected_false_flags": None if suppressed else expected[g],
                "false_flag_share": None if suppressed or total == 0 else expected[g] / total,
                "suppressed": suppressed,
            }
        )
    return rows


def subgroup_metrics(
    labels: Sequence[int],
    predictions: Sequence[int],
    groups: Sequence[str],
    min_group_size: int = 10,
    confidence: float = 0.95,
) -> list[dict]:
    """Per-subgroup FPR/FNR with exact intervals; small groups are suppressed."""
    y = np.asarray(labels, dtype=int)
    p = np.asarray(predictions, dtype=int)
    g = np.asarray(groups)
    out = []
    for name in sorted(set(g.tolist())):
        m = g == name
        n = int(m.sum())
        if n < min_group_size:
            out.append({"group": name, "n": None, "suppressed": True})
            continue
        cm = ConfusionMatrix.from_predictions(y[m], p[m])
        out.append(
            {
                "group": name,
                "n": n,
                "suppressed": False,
                "positives": cm.positives,
                "negatives": cm.negatives,
                "fpr": asdict(_rate(cm.fp, cm.negatives, confidence)),
                "fnr": asdict(_rate(cm.fn, cm.positives, confidence)),
            }
        )
    return out


def evaluate_scores(
    labels: Sequence[int],
    scores: Sequence[float],
    threshold: float,
    groups: Sequence[str] | None = None,
    probabilities_are_calibrated: bool = False,
    seed: int = 0,
) -> dict:
    """Full evaluation bundle used by the Benchmark Laboratory."""
    y, s = _validate_scores(labels, scores)
    preds = (s >= threshold).astype(int)
    cm = ConfusionMatrix.from_predictions(y, preds)
    result: dict = {
        "n": int(len(y)),
        "threshold": threshold,
        "metrics": classification_metrics(cm).to_dict(),
        "auroc": auroc(y, s),
        "auroc_ci": asdict(ci) if (ci := auroc_bootstrap_ci(y, s, n_boot=500, seed=seed)) else None,
        "roc": roc_curve(y, s),
        "pr": pr_curve(y, s),
        "operating_points": [asdict(tpr_at_fpr(y, s, f)) for f in (0.01, 0.001)],
        "calibration": None,
    }
    if probabilities_are_calibrated and ((s >= 0) & (s <= 1)).all():
        result["calibration"] = {
            "brier": brier_score(y, s),
            "ece": expected_calibration_error(y, s),
            "bins": reliability_bins(y, s),
        }
    if groups is not None:
        result["subgroups"] = subgroup_metrics(y, preds, groups)
    return result
