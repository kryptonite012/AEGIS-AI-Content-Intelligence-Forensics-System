"""API test harness: a dedicated PostgreSQL database migrated with Alembic from clean, a temporary
evidence store, and manual job execution (tests call the worker entrypoint explicitly)."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="aegis-test-"))
os.environ.update(
    {
        "AEGIS_ENVIRONMENT": "test",
        "AEGIS_DATABASE_URL": os.environ.get(
            "AEGIS_TEST_DATABASE_URL", "postgresql+psycopg://aegis:aegis-dev-only@localhost:5432/aegis_test"
        ),
        "AEGIS_STORAGE_ROOT": str(_TMP / "evidence"),
        "AEGIS_TASK_MODE": "manual",
        "AEGIS_REFERENCE_WATERMARK_KEY": "test-only-reference-watermark-key-123",
        "AEGIS_SECRET_KEY": "test-only-secret-key-0123456789abcdefghijklmnop",
    }
)
for k in [
    k
    for k in os.environ
    if k.startswith(("AEGIS_PROVIDER_", "AEGIS_TEXT_CLASSIFIER", "AEGIS_SCORING_LM", "AEGIS_C2PA_TRUST"))
]:
    del os.environ[k]

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core import ratelimit  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Test-Password-123"


def _reset_schema() -> None:
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def database():
    _reset_schema()
    from app.services.bootstrap import sync_registry, sync_roles

    with get_sessionmaker()() as db:
        sync_roles(db)
        sync_registry(db)
        db.commit()
    yield
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    ratelimit.reset_memory()
    return TestClient(app)


def _make_org(slug: str):
    from app.models import Organization, RetentionPolicy

    with get_sessionmaker()() as db:
        org = Organization(name=slug.title(), slug=slug)
        db.add(org)
        db.flush()
        db.add(RetentionPolicy(organization_id=org.id, classification="standard", retain_days=365))
        db.commit()
        return org.id


def _make_user(org_id, email: str, role: str, system_admin: bool = False):
    from app.models import Membership, User
    from app.security.passwords import hash_password

    with get_sessionmaker()() as db:
        u = User(
            email=email,
            display_name=email.split("@")[0].title(),
            password_hash=hash_password(PASSWORD),
            is_system_admin=system_admin,
        )
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, organization_id=org_id, role_id=role))
        db.commit()
        return u.id


class Actor:
    def __init__(self, client: TestClient, email: str):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.c, self.token, self.email = client, r.json()["access_token"], email

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h | kw.pop("headers", {}), **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self.h | kw.pop("headers", {}), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self.h | kw.pop("headers", {}), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self.h | kw.pop("headers", {}), **kw)


_counter = {"n": 0}


@pytest.fixture
def org(client):
    """A fresh organisation with one user per role."""
    _counter["n"] += 1
    slug = f"org{_counter['n']}"
    oid = _make_org(slug)
    roles = ["org_admin", "investigator", "forensic_analyst", "independent_reviewer", "auditor", "researcher"]
    ids = {r: _make_user(oid, f"{r}@{slug}.aegis-tests.org", r) for r in roles}
    ids["system_admin"] = _make_user(oid, f"sysadmin@{slug}.aegis-tests.org", "system_admin", system_admin=True)

    class Org:
        id = oid
        user_ids = ids

        def actor(self, role: str) -> Actor:
            email = f"sysadmin@{slug}.aegis-tests.org" if role == "system_admin" else f"{role}@{slug}.aegis-tests.org"
            return Actor(client, email)

    return Org()


def new_case(actor: Actor, reviewer_id=None, **kw) -> dict:
    _counter["n"] += 1
    body = {
        "title": "Test investigation",
        "case_reference": f"CASE-{_counter['n']}",
        "purpose": "Integration test of the AEGIS workflow.",
        "media_category": "text",
        **kw,
    }
    if reviewer_id:
        body["assigned_reviewer_id"] = str(reviewer_id)
    r = actor.post("/api/v1/investigations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def upload(actor: Actor, case_id: str, name: str, data: bytes, role: str = "primary"):
    return actor.post(f"/api/v1/investigations/{case_id}/evidence", files={"file": (name, data)}, data={"role": role})


def run_job(actor: Actor, case_id: str, evidence_id: str, profile: str = "text_triage", key: str | None = None) -> dict:
    from app.services.analysis import execute_job

    headers = {"Idempotency-Key": key} if key else {}
    r = actor.post(
        f"/api/v1/analysis/investigations/{case_id}/jobs",
        json={"evidence_item_id": evidence_id, "profile_id": profile},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    execute_job(r.json()["id"])
    return actor.get(f"/api/v1/analysis/jobs/{r.json()['id']}").json()
