"""Static PNG plots for experiment outputs (optional; requires matplotlib)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _finish(fig, ax, result: dict, path: Path) -> None:
    ax.set_title(f"{result['title']}\n{result['label']}", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_experiment(result: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    r, eid = result["results"], result["id"]
    if eid == "exp1_base_rate":
        for name, pts in r["curves"].items():
            ax.plot([p["prevalence"] for p in pts], [p["ppv"] for p in pts], marker="o", label=name)
        ax.set_xscale("log"); ax.set_xlabel("prevalence"); ax.set_ylabel("PPV"); ax.legend()
    elif eid == "exp2_subgroup":
        ax.bar([x["group"] for x in r], [x["false_flag_share"] for x in r], label="share of false flags")
        ax.scatter([x["group"] for x in r], [x["population_share"] for x in r], color="k", label="population share")
        ax.legend()
    elif eid == "exp3_corroboration":
        sim = r["simulated"]
        ax.plot([x["within_class_correlation"] for x in sim], [x["empirical_joint_fpr"] for x in sim],
                marker="o", label="empirical joint FPR")
        ax.axhline(r["assumption_based"]["fpr"], ls="--", label="independence assumption")
        ax.set_xlabel("within-class correlation"); ax.legend()
    elif eid in ("exp5_watermark_length_entropy",):
        for s in sorted({x["zipf_exponent"] for x in r}):
            pts = [x for x in r if x["zipf_exponent"] == s]
            ax.plot([p["length"] for p in pts], [p["detection_rate"] for p in pts], marker="o", label=f"zipf={s}")
        ax.set_xlabel("tokens"); ax.set_ylabel("detection rate"); ax.legend()
    elif eid == "exp6_watermark_robustness":
        ax.plot([x["replacement_fraction"] for x in r], [x["detection_rate"] for x in r], marker="o")
        ax.set_xlabel("fraction of tokens replaced"); ax.set_ylabel("detection rate")
    elif eid == "exp8_strength_distortion":
        ax.plot([x["mean_kl_nats"] for x in r], [x["detection_rate"] for x in r], marker="o")
        for x in r:
            ax.annotate(f"δ={x['delta']}", (x["mean_kl_nats"], x["detection_rate"]), fontsize=7)
        ax.set_xlabel("mean KL (nats)"); ax.set_ylabel("detection rate")
    elif eid == "exp9_fpr_calibration":
        for z in sorted({x["z_threshold"] for x in r}):
            pts = [x for x in r if x["z_threshold"] == z]
            ax.plot([p["tokens"] for p in pts], [p["exact_fpr"] for p in pts], marker="o", label=f"exact z={z}")
            ax.axhline(pts[0]["normal_approx_fpr"], ls="--", lw=1)
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("tokens"); ax.legend()
    else:
        ax.text(0.5, 0.5, "See JSON output", ha="center")
    _finish(fig, ax, result, path)
