"""Ownership is enforced before filtering/pagination, with server-selected actors."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models import AuditEvent, Incident, User, UserRole
from app.services.auth import issue_tokens


def identity(client, role=UserRole.ANALYST):
    with client.app.state.session_factory() as session:
        user = User(
            email=f"{uuid4().hex}@example.com", full_name="Test", password_hash="unused", role=role
        )
        session.add(user)
        session.flush()
        token = issue_tokens(session, user, client.app.state.settings).access_token
        session.commit()
    return user, {"Authorization": "Bearer " + token}


def upload(client, headers, **fields):
    return client.post(
        "/api/v1/incidents",
        headers=headers,
        data={"title": "Test incident", **fields},
        files={"log_file": ("synthetic.log", b"INFO GET /health 200 10ms", "text/plain")},
    )


def test_ownership_hidden_detail_admin_legacy_and_spoofing(client):
    first, first_headers = identity(client)
    second, second_headers = identity(client)
    admin, admin_headers = identity(client, UserRole.ADMIN)
    created = upload(client, first_headers, owner_user_id=second.id).json()
    other = upload(client, second_headers).json()
    with client.app.state.session_factory() as session:
        assert session.get(Incident, created["id"]).owner_user_id == first.id
        legacy = Incident(title="Legacy ownerless")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    response = client.get(f"/api/v1/incidents/{created['id']}", headers=second_headers)
    missing = client.get(f"/api/v1/incidents/{uuid4()}", headers=second_headers)
    assert response.status_code == missing.status_code == 404
    assert response.json()["error"]["code"] == missing.json()["error"]["code"]
    assert response.json()["error"]["message"] == missing.json()["error"]["message"]
    assert [row["id"] for row in client.get("/api/v1/incidents", headers=first_headers).json()] == [
        created["id"]
    ]
    assert client.get(f"/api/v1/incidents/{legacy_id}", headers=first_headers).status_code == 404
    assert client.get(f"/api/v1/incidents/{legacy_id}", headers=admin_headers).status_code == 200
    assert {row["id"] for row in client.get("/api/v1/incidents", headers=admin_headers).json()} == {
        created["id"],
        other["id"],
        legacy_id,
    }
    assert upload(client, {}).status_code == 401
    assert client.get("/api/v1/incidents").status_code == 401


def test_filters_and_pagination_are_scoped(client):
    _, headers = identity(client)
    _, other = identity(client)
    upload(client, other, title="A", environment="PROD", service_name="demo")
    wanted = upload(client, headers, title="B", environment="PROD", service_name="demo").json()
    upload(client, headers, title="C", environment="DEV")
    result = client.get(
        "/api/v1/incidents?environment=PROD&service_name=demo&status=COMPLETED&severity=LOW&sort=title&limit=1",
        headers=headers,
    )
    assert [item["id"] for item in result.json()] == [wanted["id"]]
    assert (
        client.get("/api/v1/incidents?sort=title&offset=1&limit=1", headers=headers).json()[0][
            "title"
        ]
        == "C"
    )
    for query in (
        "sort=DROP TABLE",
        "status=invalid",
        "limit=101",
        "created_from=2026-01-01T00:00:00",
        "created_from=2027-01-01T00:00:00Z&created_to=2026-01-01T00:00:00Z",
    ):
        assert client.get("/api/v1/incidents?" + query, headers=headers).status_code == 422


def test_admin_management_and_immediate_role_checks(client):
    analyst, headers = identity(client)
    admin, admin_headers = identity(client, UserRole.ADMIN)
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit-events", headers=headers).status_code == 403
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin.id}", headers=headers, json={"role": "ADMIN"}
        ).status_code
        == 403
    )
    response = client.patch(
        f"/api/v1/admin/users/{analyst.id}", headers=admin_headers, json={"role": "ADMIN"}
    )
    assert response.status_code == 200
    assert "password_hash" not in response.text
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 200
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin.id}", headers=admin_headers, json={"is_active": False}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/admin/users/{analyst.id}", headers=admin_headers, json={"is_active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/incidents", headers=headers).status_code == 401
    audit = client.get("/api/v1/admin/audit-events", headers=admin_headers)
    assert audit.status_code == 200
    assert len(audit.json()) == 2
    assert all(row["action"] == "user.updated" for row in audit.json())


def test_audit_failure_rolls_back_incident_and_file(client, monkeypatch):
    user, headers = identity(client)

    def failed(*args, **kwargs):
        raise SQLAlchemyError("private-audit-error")

    monkeypatch.setattr("app.routers.incidents.record_event", failed)
    response = upload(client, headers)
    assert response.status_code == 503
    assert "private-audit-error" not in response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Incident)) is None
    assert list(client.app.state.settings.upload_directory.glob("*")) == []


def test_creation_audit_has_no_log_or_filename(client):
    user, headers = identity(client)
    result = upload(client, headers, title="Private title").json()
    with client.app.state.session_factory() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "incident.created"))
        assert event.user_id == user.id
        assert event.resource_id == result["id"]
        assert event.safe_metadata is None


def test_first_admin_bootstrap_refuses_second(client):
    from app.auth_schemas import RegisterRequest
    from scripts.bootstrap_admin import create_first_admin

    payload = RegisterRequest(
        email="admin@example.com", password="Synthetic-password-123!", full_name="Admin"
    )
    with client.app.state.session_factory.begin() as session:
        create_first_admin(session, payload)
    with client.app.state.session_factory.begin() as session:
        with pytest.raises(RuntimeError, match="already exists"):
            create_first_admin(session, payload)


def test_permissions_smoke_script(client, capsys):
    from scripts.verify_permissions import verify

    verify(client)
    assert "PASS:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [{}, {"role": None}, {"is_active": None}, {"password_hash": "private"}, {"role": "ROOT"}],
)
def test_admin_rejects_invalid_changes(client, payload):
    target, _ = identity(client)
    _, headers = identity(client, UserRole.ADMIN)
    assert (
        client.patch(f"/api/v1/admin/users/{target.id}", headers=headers, json=payload).status_code
        == 422
    )
