"""Verify local ownership and optional administrator access without printing tokens."""

import argparse
import secrets
import time
from getpass import getpass
from uuid import uuid4

import httpx


def verify(client, admin_credentials=None):
    def check(response, status, stage):
        if response.status_code != status:
            raise RuntimeError(f"{stage}: expected {status}, received {response.status_code}.")
        return response.json()

    def login(email, password):
        data = check(
            client.post("/api/v1/auth/login", json={"email": email, "password": password}),
            200,
            "login",
        )
        return {"Authorization": "Bearer " + data["access_token"]}, data["refresh_token"]

    refresh_tokens = []
    headers = []
    try:
        for _ in range(2):
            email, password = f"permissions-{uuid4().hex}@example.com", secrets.token_urlsafe(32)
            check(
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": email,
                        "password": password,
                        "full_name": "Synthetic permissions test",
                    },
                ),
                201,
                "registration",
            )
            auth, token = login(email, password)
            headers.append(auth)
            refresh_tokens.append(token)
        incident = check(
            client.post(
                "/api/v1/incidents",
                headers=headers[0],
                data={
                    "title": "Milestone 2.3 smoke test",
                    "environment": "DEV",
                    "service_name": "permissions-demo",
                },
                files={"log_file": ("synthetic.log", b"INFO GET /health 200 10ms", "text/plain")},
            ),
            202,
            "upload",
        )
        path = "/api/v1/incidents/" + incident["id"]
        check(client.get(path), 401, "anonymous detail")
        check(client.get(path, headers=headers[1]), 404, "other analyst detail")
        check(client.get("/api/v1/admin/users", headers=headers[1]), 403, "analyst admin denial")
        items = check(
            client.get("/api/v1/incidents?service_name=permissions-demo", headers=headers[1]),
            200,
            "other analyst list",
        )
        if any(item["id"] == incident["id"] for item in items):
            raise RuntimeError("Other analyst can list the incident.")
        for _ in range(20):
            result = check(client.get(path, headers=headers[0]), 200, "owner detail")
            if result["status"] == "COMPLETED":
                break
            time.sleep(0.25)
        if result["status"] != "COMPLETED":
            raise RuntimeError("Synthetic incident did not complete.")
        if admin_credentials:
            admin, token = login(*admin_credentials)
            refresh_tokens.append(token)
            check(client.get(path, headers=admin), 200, "admin cross-owner detail")
            check(client.get("/api/v1/admin/users", headers=admin), 200, "admin users")
            events = check(
                client.get("/api/v1/admin/audit-events?limit=100", headers=admin), 200, "audit"
            )
            if not any(
                item["action"] == "incident.created" and item["resource_id"] == incident["id"]
                for item in events
            ):
                raise RuntimeError("Creation audit event was not found.")
        print(
            "PASS: authenticated upload, owner access, cross-user 404/list isolation, anonymous 401, analyst admin denial, processing."
        )
        if admin_credentials:
            print("PASS: administrator cross-owner access, user listing, and creation audit.")
        print("Two synthetic analysts and one incident remain. Incident ID:", incident["id"])
    finally:
        for token in refresh_tokens:
            client.post("/api/v1/auth/logout", json={"refresh_token": token})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin", action="store_true", help="Prompt privately for an existing administrator"
    )
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
        print(
            "Permissions verification failed; check local API/configuration. No credentials printed."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
