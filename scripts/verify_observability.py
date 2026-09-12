"""Check live readiness, error envelopes, and optional administrator audit correlation."""

import argparse
from getpass import getpass
from uuid import UUID

import httpx


def verify(client, admin_credentials=None):
    def check(response, expected, stage):
        if response.status_code != expected:
            raise RuntimeError(f"{stage}: expected {expected}, received {response.status_code}.")
        request_id = response.headers.get("x-request-id", "")
        try:
            UUID(request_id)
        except ValueError:
            raise RuntimeError(f"{stage}: request ID is missing or invalid.") from None
        if expected >= 400:
            error = response.json().get("error", {})
            if set(error) != {"code", "message", "request_id"} or error["request_id"] != request_id:
                raise RuntimeError(f"{stage}: error envelope is incorrect.")
        return request_id

    for path in ("/health", "/health/live", "/health/ready"):
        check(client.get(path), 200, path)
    first = check(client.get("/api/v1/incidents"), 401, "unauthenticated request")
    second = check(client.get("/missing-observability-test"), 404, "missing route")
    if first == second:
        raise RuntimeError("Request IDs are not unique.")
    check(client.post("/api/v1/auth/login", json={}), 422, "invalid request")
    print("PASS: liveness, readiness, unique request IDs, and 401/404/422 error envelopes.")
    if admin_credentials:
        email, password = admin_credentials
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        check(response, 200, "administrator login")
        tokens = response.json()
        headers = {"Authorization": "Bearer " + tokens["access_token"]}
        try:
            response = client.post(
                "/api/v1/incidents",
                headers=headers,
                data={"title": "Milestone 2.5 smoke test"},
                files={"log_file": ("synthetic.log", b"INFO GET /health 200 10ms", "text/plain")},
            )
            request_id = check(response, 202, "upload")
            incident_id = response.json()["id"]
            audit = client.get("/api/v1/admin/audit-events?limit=100", headers=headers)
            check(audit, 200, "audit inspection")
            if not any(
                row["resource_id"] == incident_id
                and row["action"] == "incident.created"
                and row["request_id"] == request_id
                for row in audit.json()
            ):
                raise RuntimeError("Audit request ID does not match the upload.")
            print("PASS: upload-to-audit request correlation. Request ID:", request_id)
            print("Synthetic incident retained:", incident_id)
        finally:
            client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    credentials = (
        (input("Administrator email: "), getpass("Administrator password: "))
        if args.admin
        else None
    )
    try:
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
            verify(client, credentials)
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("Observability verification failed. Check the API; no credentials printed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
