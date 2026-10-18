"""Settings used by hosted deployments without a persistent disk or Redis (see docs/operations/render.md)."""

import hashlib
import os

import pytest
from aegis_ml import fixtures
from conftest import new_case, run_job, upload


@pytest.fixture
def database_storage(monkeypatch):
    from app.core.config import get_settings
    from app.storage.base import get_storage

    monkeypatch.setattr(get_settings(), "storage_backend", "database")
    get_storage.cache_clear()
    yield get_storage()
    get_storage.cache_clear()


def test_database_backend_round_trip_and_write_once(database_storage, tmp_path):
    from app.storage.base import ObjectExists, StorageError
    from app.storage.database import CHUNK

    s = database_storage
    assert s.name == "database"
    data = os.urandom(CHUNK * 2 + 17)
    s.put_bytes("tests/db/large", data, "application/octet-stream")
    assert s.exists("tests/db/large") and b"".join(s.open("tests/db/large")) == data
    assert s.sha256("tests/db/large") == (hashlib.sha256(data).hexdigest(), len(data))
    with s.local_path("tests/db/large") as p:
        assert p.read_bytes() == data
    with pytest.raises(ObjectExists):
        s.put_bytes("tests/db/large", b"other", "text/plain")
    assert b"".join(s.open("tests/db/large")) == data

    src = tmp_path / "file.bin"
    src.write_bytes(b"from a file")
    s.put_file("tests/db/file", src, "application/octet-stream")
    assert b"".join(s.open("tests/db/file")) == b"from a file"
    s.put_bytes("tests/db/empty", b"", "text/plain")
    assert s.exists("tests/db/empty") and b"".join(s.open("tests/db/empty")) == b""

    with pytest.raises(StorageError):
        s.put_bytes("../escape", b"x", "text/plain")
    with pytest.raises(StorageError):
        list(s.open("tests/db/missing"))
    s.purge("tests/db/large")
    assert not s.exists("tests/db/large")
    ok, detail = s.health()
    assert ok and "PostgreSQL" in detail


def test_evidence_workflow_on_database_backend(database_storage, org):
    inv = org.actor("investigator")
    case = new_case(inv)
    r = upload(inv, case["id"], "notes.txt", fixtures.HUMAN_STYLE_SAMPLE.encode())
    assert r.status_code == 201, r.text
    ev = r.json()
    assert inv.post(f"/api/v1/evidence/{ev['id']}/verify").json()["intact"] is True
    job = run_job(inv, case["id"], ev["id"])
    assert job["status"] == "completed"
    assert inv.get(f"/api/v1/evidence/{ev['id']}/text").json()["text"].startswith(fixtures.HUMAN_STYLE_SAMPLE[:40])
    health = org.actor("system_admin").get("/api/v1/health/components").json()["components"]
    storage = next(c for c in health if c["id"] == "storage")
    assert storage["status"] == "operational" and storage["name"] == "Evidence storage (database)"


def test_hosted_database_urls_use_psycopg():
    from app.core.config import Settings

    for url in ("postgres://u:p@db.example.org/aegis", "postgresql://u:p@db.example.org/aegis"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@db.example.org/aegis"
    neon = "postgresql+psycopg://u:p@ep-x.neon.tech/aegis?sslmode=require"
    assert Settings(database_url=neon).database_url == neon


def test_redis_not_configured_is_reported_honestly(monkeypatch, org):
    from app.core import ratelimit
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "redis_url", "")
    ratelimit._redis.cache_clear()
    try:
        assert ratelimit._redis() is None
        health = org.actor("system_admin").get("/api/v1/health/components").json()["components"]
        redis = next(c for c in health if c["id"] == "redis")
        assert redis["status"] == "unknown" and redis["detail"].startswith("not configured")
    finally:
        ratelimit._redis.cache_clear()


def test_interrupted_jobs_are_resumed(org):
    from app.db import get_sessionmaker, utcnow
    from app.models import AnalysisJob
    from app.services.analysis import execute_job, resume_inline_jobs

    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode()).json()
    queued = inv.post(
        f"/api/v1/analysis/investigations/{case['id']}/jobs",
        json={"evidence_item_id": ev["id"], "profile_id": "text_triage"},
    ).json()["id"]
    with get_sessionmaker()() as db:
        assert resume_inline_jobs(db) >= 1
        assert db.get(AnalysisJob, queued).status == "queued"
    # A job cut off mid-run (the process restarted) is put back in the queue, then completes.
    with get_sessionmaker()() as db:
        job = db.get(AnalysisJob, queued)
        job.status, job.attempts, job.started_at = "running", 1, utcnow()
        job.runs[0].status = "running"
        db.commit()
        resume_inline_jobs(db)
        db.refresh(job)
        assert job.status == "queued" and job.runs[0].status == "pending"
    assert execute_job(queued) == "completed"
