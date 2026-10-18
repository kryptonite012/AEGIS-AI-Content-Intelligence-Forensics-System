"""Repeatable load test for the AEGIS API.

    python scripts/loadtest.py --base http://localhost:8000 --email investigator@aegis.demo \
        --password "$AEGIS_DEMO_PASSWORD" --concurrency 8 --requests 400 --jobs 20

Phases:
  1. read      - concurrent GET /investigations and GET /overview
  2. calc      - concurrent POST /evaluation/ppv (CPU-light)
  3. ingest    - sequential text uploads (hashing, sniffing, extraction, write-once storage)
  4. jobs      - text_triage jobs queued at once; measures end-to-end completion via the worker pool

Reports latency percentiles, throughput and error counts as JSON. Results depend entirely on the
hardware and configuration used; record those alongside any numbers you publish.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import time
import uuid

import httpx


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, round(p / 100 * (len(xs) - 1))))
    return round(xs[k] * 1000, 1)


def summary(name: str, lat: list[float], errors: int, wall: float) -> dict:
    return {
        "phase": name,
        "requests": len(lat) + errors,
        "errors": errors,
        "throughput_rps": round(len(lat) / wall, 1) if wall else None,
        "p50_ms": pct(lat, 50),
        "p95_ms": pct(lat, 95),
        "p99_ms": pct(lat, 99),
        "mean_ms": round(statistics.fmean(lat) * 1000, 1) if lat else None,
    }


async def hammer(client: httpx.AsyncClient, n: int, conc: int, make) -> tuple[list[float], int, float]:  # type: ignore[no-untyped-def]
    lat: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(conc)

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            t = time.perf_counter()
            try:
                r = await make(i)
                if r.status_code >= 400:
                    errors += 1
                    return
                lat.append(time.perf_counter() - t)
            except httpx.HTTPError:
                errors += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n)))
    return lat, errors, time.perf_counter() - t0


async def main(a: argparse.Namespace) -> dict:
    async with httpx.AsyncClient(base_url=a.base, timeout=120, trust_env=False) as c:
        r = await c.post("/api/v1/auth/login", json={"email": a.email, "password": a.password})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        out = []
        lat, err, wall = await hammer(
            c,
            a.requests,
            a.concurrency,
            lambda i: c.get("/api/v1/investigations" if i % 2 else "/api/v1/overview", headers=h),
        )
        out.append(summary("read (list investigations / overview)", lat, err, wall))
        body = {"prevalence": 0.05, "tpr": 0.9, "fpr": 0.05, "sample_size": 10000}
        lat, err, wall = await hammer(
            c, a.requests, a.concurrency, lambda i: c.post("/api/v1/evaluation/ppv", json=body, headers=h)
        )
        out.append(summary("calc (PPV calculator)", lat, err, wall))

        case = await c.post(
            "/api/v1/investigations",
            headers=h,
            json={
                "title": "Load test",
                "case_reference": f"LOAD-{uuid.uuid4().hex[:8]}",
                "media_category": "text",
                "purpose": "Synthetic load test; contains generated filler text only.",
            },
        )
        case.raise_for_status()
        cid = case.json()["id"]
        text = ("The survey team recorded water levels at the north gauge every morning. " * 40).encode()
        lat, err, ids = [], 0, []
        t0 = time.perf_counter()
        for i in range(a.jobs):
            t = time.perf_counter()
            r = await c.post(
                f"/api/v1/investigations/{cid}/evidence",
                headers=h,
                files={"file": (f"load-{i}.txt", text + str(i).encode())},
            )
            if r.status_code == 201:
                lat.append(time.perf_counter() - t)
                ids.append(r.json()["id"])
            else:
                err += 1
        out.append(summary("ingest (text upload, sequential)", lat, err, time.perf_counter() - t0))

        t0 = time.perf_counter()
        jobs = []
        for ev in ids:
            r = await c.post(
                f"/api/v1/analysis/investigations/{cid}/jobs",
                headers=h,
                json={"evidence_item_id": ev, "profile_id": "text_triage"},
            )
            if r.status_code == 202:
                jobs.append(r.json()["id"])
        pending = set(jobs)
        done_at: dict[str, float] = {}
        statuses: dict[str, str] = {}
        while pending and time.perf_counter() - t0 < a.job_timeout:
            for j in list(pending):
                s = (await c.get(f"/api/v1/analysis/jobs/{j}", headers=h)).json()["status"]
                if s in ("completed", "completed_with_failures", "failed", "cancelled"):
                    pending.discard(j)
                    done_at[j] = time.perf_counter() - t0
                    statuses[s] = statuses.get(s, 0) + 1
            await asyncio.sleep(0.25)
        wall = time.perf_counter() - t0
        out.append(
            {
                "phase": "jobs (text_triage, queued together)",
                "jobs": len(jobs),
                "completed": len(done_at),
                "timed_out": len(pending),
                "statuses": statuses,
                "wall_s": round(wall, 2),
                "jobs_per_minute": round(len(done_at) / wall * 60, 1) if wall else None,
                "p50_completion_s": round(statistics.median(done_at.values()), 2) if done_at else None,
                "max_completion_s": round(max(done_at.values()), 2) if done_at else None,
            }
        )
        return {
            "base_url": a.base,
            "concurrency": a.concurrency,
            "python": platform.python_version(),
            "host": {"platform": platform.platform(), "cpus": os.cpu_count()},
            "results": out,
        }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--email", default="investigator@aegis.demo")
    p.add_argument("--password", default=os.environ.get("AEGIS_DEMO_PASSWORD", "Aegis-Demo-Only-2026"))
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--requests", type=int, default=400)
    p.add_argument("--jobs", type=int, default=20)
    p.add_argument("--job-timeout", type=float, default=600)
    print(json.dumps(asyncio.run(main(p.parse_args())), indent=2))
