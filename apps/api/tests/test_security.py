"""Access control, tenant isolation, malicious input, rate limiting and secret handling."""

import zipfile

import pytest
from aegis_ml import fixtures
from conftest import PASSWORD, new_case, upload


def test_requires_authentication(client):
    for url in ("/api/v1/investigations", "/api/v1/overview", "/api/v1/audit/events", "/api/v1/evidence"):
        r = client.get(url)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    r = client.get("/api/v1/investigations", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_error_format_and_headers(org):
    a = org.actor("investigator")
    r = a.get("/api/v1/investigations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "not_found" and body["correlation_id"] == r.headers["X-Request-ID"]
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]


def test_role_permissions_enforced_server_side(org):
    researcher = org.actor("researcher")
    auditor = org.actor("auditor")
    inv = org.actor("investigator")
    assert researcher.get("/api/v1/investigations").status_code == 403
    assert (
        researcher.post("/api/v1/evaluation/ppv", json={"prevalence": 0.05, "tpr": 0.9, "fpr": 0.05}).status_code == 200
    )
    case = new_case(inv)
    assert (
        auditor.post(
            "/api/v1/investigations",
            json={"title": "x" * 5, "case_reference": "A-1", "purpose": "p" * 20, "media_category": "text"},
        ).status_code
        == 403
    )
    assert auditor.get(f"/api/v1/investigations/{case['id']}").status_code == 200
    assert upload(auditor, case["id"], "a.txt", b"hello world " * 20).status_code == 403
    assert inv.get("/api/v1/audit/events").status_code == 403
    assert inv.get("/api/v1/users").status_code == 403
    assert org.actor("org_admin").get("/api/v1/users").status_code == 200


def test_cross_tenant_isolation(org, client):
    from conftest import Actor, _make_org, _make_user

    other_id = _make_org("othertenant" + str(id(org)))
    _make_user(other_id, f"spy{id(org)}@other.aegis-tests.org", "system_admin")
    spy = Actor(client, f"spy{id(org)}@other.aegis-tests.org")
    inv = org.actor("investigator")
    case = new_case(inv)
    ev = upload(inv, case["id"], "a.txt", (fixtures.HUMAN_STYLE_SAMPLE).encode()).json()
    for url in (
        f"/api/v1/investigations/{case['id']}",
        f"/api/v1/evidence/{ev['id']}",
        f"/api/v1/investigations/{case['id']}/evidence",
        f"/api/v1/evidence/{ev['id']}/text",
        f"/api/v1/investigations/{case['id']}/history",
    ):
        assert spy.get(url).status_code == 404, url
    assert spy.post(f"/api/v1/evidence/{ev['id']}/verify").status_code == 404
    assert (
        spy.post(
            f"/api/v1/analysis/investigations/{case['id']}/jobs",
            json={"evidence_item_id": ev["id"], "profile_id": "text_triage"},
        ).status_code
        == 404
    )
    assert all(c["id"] != case["id"] for c in spy.get("/api/v1/investigations").json()["items"])
    # Choosing another organisation via header is refused for non-members.
    r = spy.get("/api/v1/investigations", headers={"X-AEGIS-Organization": str(org.id)})
    assert r.status_code == 403


def test_restricted_classification(org):
    inv = org.actor("investigator")
    analyst = org.actor("forensic_analyst")
    case = new_case(inv, access_classification="restricted")
    assert analyst.get(f"/api/v1/investigations/{case['id']}").status_code == 404
    assert org.actor("auditor").get(f"/api/v1/investigations/{case['id']}").status_code == 200


@pytest.mark.parametrize(
    "name,payload,code",
    [
        ("evil.exe", b"MZ\x90\x00" + b"\x00" * 100, "unsupported_media"),
        ("script.sh", b"#!/bin/sh\nrm -rf /\n", "unsupported_media"),
        ("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "malformed_media"),
        ("../../etc/passwd", b"\x00\x01\x02\x03", "unsupported_media"),
    ],
)
def test_malicious_uploads_rejected(org, name, payload, code):
    inv = org.actor("investigator")
    case = new_case(inv)
    r = upload(inv, case["id"], name, payload)
    assert r.status_code in (400, 415), r.text
    assert r.json()["error"]["code"] == code


def test_zip_traversal_and_bomb_rejected(org, tmp_path):
    inv = org.actor("investigator")
    case = new_case(inv)
    p = tmp_path / "x.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("word/document.xml", "x")
        z.writestr("../evil", "x")
    assert upload(inv, case["id"], "x.docx", p.read_bytes()).status_code == 415
    bomb = fixtures.make_zip_bomb_like(tmp_path / "b.docx")
    assert upload(inv, case["id"], "b.docx", bomb.read_bytes()).status_code == 415


def test_oversized_upload(org, monkeypatch):
    from app.core.config import get_settings

    inv = org.actor("investigator")
    case = new_case(inv)
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = upload(inv, case["id"], "big.txt", b"a" * (1024 * 1024 + 10))
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_filename_is_sanitised(org):
    inv = org.actor("investigator")
    case = new_case(inv)
    r = upload(inv, case["id"], "../../../tmp/\x00evil\n.txt", fixtures.HUMAN_STYLE_SAMPLE.encode())
    assert r.status_code == 201
    assert "/" not in r.json()["display_name"] and "\x00" not in r.json()["display_name"]


def test_login_rate_limit_and_lockout(org, client):
    email = f"investigator@{_slug(org)}.aegis-tests.org"
    codes = [
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes
    assert codes[0] == 401


def _slug(org):
    from app.db import get_sessionmaker
    from app.models import Organization

    with get_sessionmaker()() as db:
        return db.get(Organization, org.id).slug


def test_session_revocation(org, client):
    a = org.actor("investigator")
    assert a.post("/api/v1/auth/logout").status_code == 204
    assert a.get("/api/v1/investigations").status_code == 401


def test_refresh_requires_csrf_header(org, client):
    email = f"analyst-csrf{id(org)}@x.aegis-tests.org"
    from conftest import _make_user

    _make_user(org.id, email, "forensic_analyst")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert "aegis_refresh" in r.cookies or "aegis_refresh" in client.cookies
    assert client.post("/api/v1/auth/refresh").status_code == 403
    r2 = client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "aegis-web"})
    assert r2.status_code == 200 and r2.json()["access_token"]


def test_no_secrets_in_responses(org):
    inv = org.actor("investigator")
    me = inv.get("/api/v1/auth/me").text
    assert "password_hash" not in me and "mfa_secret" not in me
    health = org.actor("system_admin").get("/api/v1/health/components").text
    assert "test-only-reference-watermark-key-123" not in health
    assert "test-only-secret-key" not in health
    settings = org.actor("org_admin").get("/api/v1/admin/settings").text
    assert "secret_key" not in settings and "database_url" not in settings


def test_sql_injection_in_filters_is_inert(org):
    inv = org.actor("investigator")
    r = inv.get("/api/v1/investigations", params={"q": "' OR 1=1; DROP TABLE users; --"})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert inv.get("/api/v1/auth/me").status_code == 200


def test_report_tampering_detected(org):
    from app.db import get_sessionmaker
    from app.models import Report

    inv = org.actor("investigator")
    case = new_case(inv)
    upload(inv, case["id"], "a.txt", fixtures.HUMAN_STYLE_SAMPLE.encode())
    rep = inv.post(f"/api/v1/investigations/{case['id']}/reports").json()
    with get_sessionmaker()() as db:
        r = db.get(Report, rep["id"])
        payload = dict(r.payload)
        payload["case"] = {**payload["case"], "title": "Tampered title"}
        r.payload = payload
        db.commit()
    v = inv.post(f"/api/v1/reports/{rep['id']}/verify").json()
    assert v["json_integrity"] is False and v["intact"] is False


def test_audit_tampering_detected(org):
    from app.db import get_sessionmaker
    from app.models import AuditEvent
    from sqlalchemy import select, text

    inv = org.actor("investigator")
    new_case(inv)
    aud = org.actor("auditor")
    assert aud.post("/api/v1/audit/verify").json()["valid"] is True
    with get_sessionmaker()() as db:
        ev = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one()
        original = ev.details
        db.execute(text("UPDATE audit_events SET details = '{\"forged\": true}' WHERE seq = :s"), {"s": ev.seq})
        db.commit()
        result = aud.post("/api/v1/audit/verify").json()
        assert result["valid"] is False and result["broken_at_seq"] == ev.seq
        db.execute(
            text("UPDATE audit_events SET details = CAST(:d AS jsonb) WHERE seq = :s"),
            {"d": __import__("json").dumps(original), "s": ev.seq},
        )
        db.commit()
