"""Exercise local multi-file APIs without printing credentials or file keys."""

import hashlib
import time
from getpass import getpass

import httpx


def verify(client, email, password):
    def check(response, expected, stage):
        if response.status_code != expected:
            raise RuntimeError(f"{stage}: expected {expected}, received {response.status_code}.")
        return response.json() if expected != 204 else None

    tokens = check(
        client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200, "login"
    )
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    try:
        bodies = [b"INFO GET /health 200 10ms\n", b"INFO GET /other 200 20ms\n"]
        created = check(
            client.post(
                "/api/v1/incidents",
                headers=headers,
                data={"title": "Milestone 2.4 smoke test"},
                files=[
                    ("log_files", (f"sample{i}.log", body, "text/plain"))
                    for i, body in enumerate(bodies)
                ],
            ),
            202,
            "create",
        )
        path = "/api/v1/incidents/" + created["id"]

        def completed(expected_events):
            for _ in range(40):
                detail = check(client.get(path, headers=headers), 200, "detail")
                if detail["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(0.25)
            if (
                detail["status"] != "COMPLETED"
                or detail["statistics"]["total_events"] != expected_events
            ):
                raise RuntimeError("Combined processing verification failed.")

        completed(2)
        rows = check(client.get(path + "/files", headers=headers), 200, "file list")
        if len(rows) != 2 or rows[0]["sha256"] != hashlib.sha256(bodies[0]).hexdigest():
            raise RuntimeError("File metadata/checksum verification failed.")
        if any("storage_key" in row or "storage_scope" in row for row in rows):
            raise RuntimeError("File response exposed storage internals.")
        check(
            client.post(
                path + "/files",
                headers=headers,
                files={"log_files": ("extra.txt", b"INFO GET /extra 200 5ms\n", "text/plain")},
            ),
            202,
            "attach",
        )
        completed(3)
        rows = check(client.get(path + "/files", headers=headers), 200, "file list")
        for index, row in enumerate(rows):
            check(client.delete(path + "/files/" + row["id"], headers=headers), 204, "delete")
            if index < len(rows) - 1:
                completed(len(rows) - index - 1)
        detail = check(client.get(path, headers=headers), 200, "empty incident")
        if detail["status"] != "CREATED" or detail["analysis"] is not None:
            raise RuntimeError("Empty incident state is incorrect.")
        if check(client.get(path + "/files", headers=headers), 200, "empty file list"):
            raise RuntimeError("Deleted file metadata remains.")
        print(
            "PASS: multiple uploads, SHA-256, private metadata, combined analysis, attachment, deletion, empty state."
        )
        print("Synthetic empty incident retained:", created["id"])
    finally:
        client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})


def main():
    email = input("Account email: ")
    password = getpass("Account password: ")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
            verify(client, email, password)
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("File verification failed; check the local API. No credentials printed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
