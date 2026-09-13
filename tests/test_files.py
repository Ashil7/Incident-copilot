"""Multi-file transactions, integrity, permissions, and retriable cleanup."""

import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Incident, IncidentStatus, LogFile, StorageDeletion, User
from app.services.auth import issue_tokens
from app.services.incident_files import cleanup_pending, file_rows
from app.services.pipeline import run_analysis
from app.services.storage import LocalStorage, get_storage


@pytest.fixture(autouse=True)
def authenticate(incident_user):
    pass


def create(client, bodies=None):
    bodies = bodies or [b"INFO GET /health 200 10ms\n", b"INFO GET /other 200 20ms\n"]
    return client.post(
        "/api/v1/incidents",
        data={"title": "Multiple files"},
        files=[
            ("log_files", (f"file{i}.log", body, "text/plain")) for i, body in enumerate(bodies)
        ],
    )


def test_multiple_files_checksums_metadata_and_combined_statistics(client):
    created = create(client)
    assert created.status_code == 202
    incident_id = created.json()["id"]
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "COMPLETED"
    assert detail["statistics"]["total_events"] == 2
    metadata = client.get(f"/api/v1/incidents/{incident_id}/files").json()
    assert len(metadata) == 2
    assert all("storage_key" not in row and "storage_scope" not in row for row in metadata)
    assert metadata[0]["sha256"] == hashlib.sha256(b"INFO GET /health 200 10ms\n").hexdigest()
    assert metadata[0]["size_bytes"] == len(b"INFO GET /health 200 10ms\n")


def test_invalid_second_file_rolls_back_entire_create(client):
    assert create(client, [b"INFO ok", b"\xff"]).status_code == 422
    assert client.get("/api/v1/incidents").json() == []
    assert list(client.app.state.settings.upload_directory.glob("*")) == []


def test_attach_delete_and_final_empty_state(client):
    incident_id = create(client).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    added = client.post(
        path,
        files=[
            ("log_files", ("extra.json", b'{"level":"INFO","message":"ok"}', "application/json"))
        ],
    )
    assert added.status_code == 202
    assert client.get(f"/api/v1/incidents/{incident_id}").json()["statistics"]["total_events"] == 3
    for row in client.get(path).json():
        assert client.delete(path + "/" + row["id"]).status_code == 204
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "CREATED"
    assert detail["analysis"] is None and detail["statistics"] is None
    assert client.get(path).json() == []
    assert list(client.app.state.settings.upload_directory.glob("*")) == []


def test_failed_attachment_preserves_existing_files_and_analysis(client):
    incident_id = create(client).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    before = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert (
        client.post(
            path,
            files=[
                ("log_files", ("ok.log", b"INFO", "text/plain")),
                ("log_files", ("bad.log", b"\x00", "text/plain")),
            ],
        ).status_code
        == 422
    )
    assert len(client.get(path).json()) == 2
    assert client.get(f"/api/v1/incidents/{incident_id}").json() == before
    assert len(list(client.app.state.settings.upload_directory.glob("*"))) == 2


def test_active_pipeline_blocks_mutation(client, monkeypatch):
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    incident_id = create(client).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    row = client.get(path).json()[0]
    assert client.delete(path + "/" + row["id"]).status_code == 409
    assert (
        client.post(path, files={"log_files": ("new.log", b"INFO", "text/plain")}).status_code
        == 409
    )


def test_deletion_failure_is_queued_and_retried(client, monkeypatch):
    incident_id = create(client, [b"INFO"]).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    row = client.get(path).json()[0]
    original = LocalStorage.delete

    def unavailable(*args):
        raise OSError("synthetic unavailable storage")

    monkeypatch.setattr(LocalStorage, "delete", unavailable)
    assert client.delete(path + "/" + row["id"]).status_code == 204
    with client.app.state.session_factory() as session:
        assert session.scalar(select(StorageDeletion)) is not None
        assert session.get(LogFile, row["id"]) is None
    monkeypatch.setattr(LocalStorage, "delete", original)
    assert cleanup_pending(client.app.state.session_factory, client.app.state.settings) == 1
    assert cleanup_pending(client.app.state.session_factory, client.app.state.settings) == 0


def test_delete_database_failure_preserves_object(client, monkeypatch):
    incident_id = create(client, [b"INFO"]).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    row = client.get(path).json()[0]
    with monkeypatch.context() as patch:

        def failed(*args):
            raise SQLAlchemyError("private failure")

        patch.setattr(Session, "commit", failed)
        assert client.delete(path + "/" + row["id"]).status_code == 503
    assert client.get(path).json() == [row]
    assert len(list(client.app.state.settings.upload_directory.glob("*"))) == 1


def test_checksum_failure_and_evidence_provenance(client):
    incident_id = create(client, [b"ERROR failed\n", b"ERROR other\n"]).json()["id"]
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    evidence = detail["statistics"]["evidence"]
    assert len({item["event"]["source_file_id"] for item in evidence}) == 2
    assert {item["event"]["line_number"] for item in evidence} == {1, 2}
    assert all(item["event"]["source_line_number"] == 1 for item in evidence)
    with client.app.state.session_factory() as session:
        row = file_rows(session, incident_id)[0]
        get_storage(client.app.state.settings).path(row.storage_key).write_bytes(
            b"X" * row.size_bytes
        )
        incident = session.get(Incident, incident_id)
        incident.status = IncidentStatus.UPLOADED
        incident.statistics = None
        session.commit()
    run_analysis(incident_id, client.app.state.session_factory, client.app.state.settings)
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "FAILED" and detail["statistics"] is None


def test_cross_user_files_hidden_and_file_count_limit(client):
    incident_id = create(client).json()["id"]
    path = f"/api/v1/incidents/{incident_id}/files"
    row = client.get(path).json()[0]
    with client.app.state.session_factory() as session:
        user = User(email="other-files@example.com", full_name="Other", password_hash="unused")
        session.add(user)
        session.flush()
        token = issue_tokens(session, user, client.app.state.settings).access_token
        session.commit()
    headers = {"Authorization": "Bearer " + token}
    assert client.get(path, headers=headers).status_code == 404
    assert client.delete(path + "/" + row["id"], headers=headers).status_code == 404
    assert (
        client.post(
            path, headers=headers, files={"log_files": ("new.log", b"INFO", "text/plain")}
        ).status_code
        == 404
    )
    client.app.state.settings.max_files_per_incident = 2
    assert (
        client.post(path, files={"log_files": ("new.log", b"INFO", "text/plain")}).status_code
        == 422
    )


def test_local_storage_rejects_paths_and_wrong_scope_cleanup(client, tmp_path):
    storage = LocalStorage(tmp_path)
    for key in ("../secret.log", "/tmp/secret.log", "not-a-uuid.log"):
        with pytest.raises(ValueError):
            storage.open(key)
    with client.app.state.session_factory() as session:
        session.add(StorageDeletion(storage_key=f"{uuid4()}.log", storage_scope=storage.scope))
        session.commit()
    assert cleanup_pending(client.app.state.session_factory, client.app.state.settings) == 0


def test_storage_contract_accepts_memory_adapter(client):
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    from app.services.storage import StoredObject
    from app.services.uploads import store_upload

    class MemoryStorage:
        def put(self, chunks, suffix):
            self.data = b"".join(chunks)
            return StoredObject("opaque", len(self.data), hashlib.sha256(self.data).hexdigest())

    storage = MemoryStorage()
    upload = UploadFile(
        filename="test.log", file=BytesIO(b"INFO"), headers=Headers({"content-type": "text/plain"})
    )
    result = store_upload(upload, client.app.state.settings, storage)
    assert result.size == 4 and storage.data == b"INFO"


def test_legacy_file_is_adopted_without_copying(client, incident_user):
    storage = get_storage(client.app.state.settings)
    item = storage.put([b"INFO GET /old 200 10ms\n"], ".log")
    with client.app.state.session_factory() as session:
        incident = Incident(
            title="Legacy",
            owner_user_id=incident_user.id,
            status=IncidentStatus.COMPLETED,
            original_filename="old.log",
            stored_file_path=str(storage.path(item.key)),
        )
        session.add(incident)
        session.commit()
        incident_id = incident.id
    path = f"/api/v1/incidents/{incident_id}/files"
    assert client.get(path).json() == []
    assert (
        client.post(
            path, files={"log_files": ("new.log", b"INFO GET /new 200 10ms", "text/plain")}
        ).status_code
        == 202
    )
    assert len(client.get(path).json()) == 2
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["statistics"]["total_events"] == 2
    assert storage.path(item.key).is_file()
    assert len(list(storage.root.iterdir())) == 2


def test_unavailable_legacy_file_prevents_attachment(client, incident_user):
    with client.app.state.session_factory() as session:
        incident = Incident(
            title="Unavailable legacy",
            owner_user_id=incident_user.id,
            status=IncidentStatus.COMPLETED,
            stored_file_path="/other-environment/missing.log",
        )
        session.add(incident)
        session.commit()
        incident_id = incident.id
    response = client.post(
        f"/api/v1/incidents/{incident_id}/files",
        files={"log_files": ("new.log", b"INFO", "text/plain")},
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/incidents/{incident_id}").json()["status"] == "COMPLETED"


def test_live_file_script_contract(client):
    from app.services.auth import password_hasher
    from scripts.verify_files import verify

    with client.app.state.session_factory() as session:
        session.add(
            User(
                email="file-script@example.com",
                full_name="Script",
                password_hash=password_hasher.hash("Synthetic-password-123!"),
            )
        )
        session.commit()
    verify(client, "file-script@example.com", "Synthetic-password-123!")
