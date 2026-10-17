"""Run reliability experiments and write machine-readable outputs plus a manifest.

python -m aegis_research.experiments --all --out research/results
python -m aegis_research.experiments exp1_base_rate exp9_fpr_calibration --plots
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import scipy

from aegis_research import __version__
from aegis_research.experiments.catalog import EXPERIMENTS


def _jsonable(o):
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return str(o)
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.generic):
        return _jsonable(o.item())
    return o


def run(ids: list[str], out: Path, plots: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for exp_id in ids:
        result = _jsonable(EXPERIMENTS[exp_id]())
        payload = json.dumps(result, indent=2, sort_keys=True)
        path = out / f"{exp_id}.json"
        path.write_text(payload)
        entries.append(
            {
                "id": exp_id,
                "kind": result["kind"],
                "file": path.name,
                "sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "config_sha256": hashlib.sha256(json.dumps(result["config"], sort_keys=True).encode()).hexdigest(),
            }
        )
        if plots:
            from aegis_research.experiments.plots import plot_experiment

            plot_experiment(result, out / f"{exp_id}.png")
        print(f"[{result['kind']:>10}] {exp_id}: {result['title']}")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "aegis_research_version": __version__,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "platform": platform.platform(),
        "experiments": entries,
        "disclaimer": "Analytical and simulated results only. None of these outputs measure a deployed "
        "detector on real content.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ids", nargs="*", help=f"experiment ids: {', '.join(EXPERIMENTS)}")
    p.add_argument("--all", action="store_true")
    p.add_argument("--out", type=Path, default=Path("research/results"))
    p.add_argument("--plots", action="store_true", help="also write PNG plots (requires matplotlib)")
    a = p.parse_args()
    unknown = sorted(set(a.ids) - set(EXPERIMENTS))
    if unknown:
        p.error(f"unknown experiment ids: {unknown}")
    ids = list(EXPERIMENTS) if a.all or not a.ids else a.ids
    run(ids, a.out, a.plots)


if __name__ == "__main__":
    main()
