"""Upload validation, storage cleanup, and incident API contracts."""

from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def isolate_upload_tests(monkeypatch: pytest.MonkeyPatch, incident_user, client) -> None:
    # Pipeline execution has its own integration tests; keep these focused on storage.
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)


def upload(client: TestClient, name: str = "sample.log", body: bytes = b"INFO synthetic\n"):
    return client.post(
        "/api/v1/incidents",
        data={"title": " Synthetic incident ", "environment": "DEV"},
        files={"log_file": (name, body, "text/plain")},
    )


def stored_files(client: TestClient) -> list[Path]:
    return list(client.app.state.settings.upload_directory.glob("*"))


def test_create_list_detail_and_safe_filename(client: TestClient) -> None:
    response = upload(client, "../../escape.log")
    assert response.status_code == 202
    item = response.json()
    assert item["title"] == "Synthetic incident"
    assert item["status"] == "UPLOADED"
    assert item["analysis"] is None
    assert item["created_at"].endswith("Z")
    assert "stored_file_path" not in item
    UUID(item["id"])
    files = stored_files(client)
    assert len(files) == 1
    UUID(files[0].stem)
    assert files[0].read_bytes() == b"INFO synthetic\n"
    assert client.get(f"/api/v1/incidents/{item['id']}").json() == item
    assert client.get("/api/v1/incidents").json() == [item]


@pytest.mark.parametrize(
    "name,body,status",
    [
        ("test.exe", b"data", 422),
        ("test.log", b"", 422),
        ("test.log", b"\xff", 422),
        ("test.txt", b"a\x00b", 422),
    ],
)
def test_rejected_files_leave_no_data(client: TestClient, name: str, body: bytes, status: int):
    assert upload(client, name, body).status_code == status
    assert stored_files(client) == []
    assert client.get("/api/v1/incidents").json() == []


def test_size_limit_and_partial_cleanup(client: TestClient) -> None:
    client.app.state.settings.max_upload_size_mb = 1
    assert upload(client, body=b"a" * (1024 * 1024 + 1)).status_code == 413
    assert stored_files(client) == []
    assert upload(client, body=b"a" * (1024 * 1024)).status_code == 202


@pytest.mark.parametrize(
    "fields",
    [
        {"title": " "},
        {"title": "x" * 201},
        {"title": "ok", "environment": "STAGE"},
        {"title": "ok", "service_name": "x" * 201},
    ],
)
def test_invalid_metadata(client: TestClient, fields: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/incidents", data=fields, files={"log_file": ("test.log", b"INFO", "text/plain")}
    )
    assert response.status_code == 422
    assert stored_files(client) == []


def test_rejects_spoofed_content_type(client: TestClient) -> None:
    response = client.post(
        "/api/v1/incidents",
        data={"title": "test"},
        files={"log_file": ("test.log", b"INFO", "image/png")},
    )
    assert response.status_code == 422
    assert stored_files(client) == []


def test_database_failure_removes_file(client: TestClient) -> None:
    with patch.object(Session, "commit", side_effect=SQLAlchemyError("private database details")):
        response = upload(client)
    assert response.status_code == 503
    assert "private database details" not in response.text
    assert stored_files(client) == []
    assert client.get("/api/v1/incidents").json() == []


def test_pagination_and_missing_id(client: TestClient) -> None:
    first = upload(client).json()
    second = upload(client).json()
    assert client.get("/api/v1/incidents?limit=1").json()[0]["id"] == second["id"]
    assert client.get("/api/v1/incidents?limit=1&offset=1").json()[0]["id"] == first["id"]
    assert client.get("/api/v1/incidents?limit=101").status_code == 422
    assert client.get("/api/v1/incidents?offset=-1").status_code == 422
    assert client.get(f"/api/v1/incidents/{uuid4()}").status_code == 404
    assert client.get("/api/v1/incidents/not-a-uuid").status_code == 422
