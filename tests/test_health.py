"""Public HTTP contracts for the Milestone 1.1 application."""

from fastapi.testclient import TestClient


def test_health_without_external_services(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_swagger_page(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_openapi_documents_health(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "AI Incident Copilot"
    assert {"/health", "/health/ready"} <= set(schema["paths"])
    assert "200" in schema["paths"]["/health"]["get"]["responses"]


def test_unknown_route(client: TestClient) -> None:
    assert client.get("/missing").status_code == 404
