"""Verify queued uploads and worker completion with synthetic data only."""

import argparse
from getpass import getpass
from time import monotonic, sleep
from uuid import UUID

import httpx


def verify(client, email, password, *, incident_id=None, expect_queued=False):
    def check(response, status):
        if response.status_code != status:
            raise RuntimeError(f"Expected HTTP {status}, received {response.status_code}.")
        return response.json()

    tokens = check(
        client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200
    )
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    try:
        if incident_id is None:
            response = client.post(
                "/api/v1/incidents",
                headers=headers,
                data={"title": "Milestone 3.1 queue smoke test"},
                files={"log_file": ("healthy.log", b"INFO GET /health 200 10ms\n", "text/plain")},
            )
            incident_id = check(response, 202)["id"]
            print("Upload request ID:", response.headers.get("x-request-id"))
        print("Synthetic incident retained:", incident_id)
        path = f"/api/v1/incidents/{incident_id}"
        deadline = monotonic() + (3 if expect_queued else 60)
        while True:
            detail = check(client.get(path, headers=headers), 200)
            if expect_queued:
                if detail["status"] != "UPLOADED" or detail["analysis"] is not None:
                    raise RuntimeError(
                        "Expected an unprocessed upload; stop all workers for this check."
                    )
                if monotonic() >= deadline:
                    print("PASS: incident stayed queued while the worker was stopped.")
                    return
            elif detail["status"] == "COMPLETED":
                if (
                    detail["statistics"]["total_events"] != 1
                    or detail["analysis"]["provider"] != "deterministic"
                ):
                    raise RuntimeError("Unexpected synthetic analysis result.")
                print("PASS: queued synthetic incident completed with persisted analysis.")
                return
            elif detail["status"] == "FAILED":
                raise RuntimeError("Worker reported a failed incident; inspect safe worker logs.")
            if monotonic() >= deadline:
                raise RuntimeError("Completion timed out; check worker readiness.")
            sleep(0.5)
    finally:
        client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--incident", type=UUID)
    group.add_argument("--expect-queued", action="store_true")
    args = parser.parse_args()
    email, password = input("Account email: "), getpass("Account password: ")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
            verify(
                client,
                email,
                password,
                incident_id=str(args.incident) if args.incident else None,
                expect_queued=args.expect_queued,
            )
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("Queue verification failed. No credentials printed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
