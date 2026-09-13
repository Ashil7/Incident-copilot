"""Verify persisted job progress and retry eligibility without a provider call."""

from getpass import getpass
from time import monotonic, sleep

import httpx


def verify(client, email, password):
    def check(response, expected):
        if response.status_code != expected:
            raise RuntimeError(f"Expected HTTP {expected}, received {response.status_code}.")
        return response.json()

    tokens = check(
        client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200
    )
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    try:
        created = check(
            client.post(
                "/api/v1/incidents",
                headers=headers,
                data={"title": "Milestone 3.2 retry smoke test"},
                files={"log_file": ("healthy.log", b"INFO GET /health 200 10ms", "text/plain")},
            ),
            202,
        )
        path = f"/api/v1/incidents/{created['id']}"
        print("Synthetic incident retained:", created["id"])

        def terminal(expected):
            deadline = monotonic() + 60
            while True:
                latest = check(client.get(path + "/jobs/latest", headers=headers), 200)
                if latest["status"] in ("FAILED", "COMPLETED"):
                    if latest["status"] != expected:
                        raise RuntimeError("Unexpected terminal job state.")
                    return latest
                if monotonic() >= deadline:
                    raise RuntimeError("Job polling timed out.")
                sleep(0.5)

        first = terminal("COMPLETED")
        if first["attempt_count"] != 1 or first["progress"] != 100:
            raise RuntimeError("Completion progress is incorrect.")
        analysis = check(client.get(path + "/analysis", headers=headers), 200)
        detail = check(client.get(path, headers=headers), 200)
        if (
            analysis["provider"] != "deterministic"
            or analysis["prompt_version"] is not None
            or analysis["input_tokens"] is not None
            or analysis["output_tokens"] is not None
            or analysis["result"] != detail["analysis"]["result"]
        ):
            raise RuntimeError("Normalized provider metadata is incorrect.")
        response = client.post(path + "/analysis/retry", headers=headers)
        if response.status_code != 409:
            raise RuntimeError("A completed job must not qualify for failed-job retry.")
        requested = check(client.post(path + "/analysis", headers=headers), 202)
        second = terminal("COMPLETED")
        if first["id"] == second["id"] or requested["id"] != second["id"]:
            raise RuntimeError("Explicit reanalysis did not create a distinct job.")
        print(
            "PASS: job progress, retry eligibility, explicit reanalysis, and normalized deterministic provider metadata."
        )
    finally:
        client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})


def main():
    email, password = input("Account email: "), getpass("Account password: ")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8001", timeout=20, trust_env=False) as client:
            verify(client, email, password)
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("Job verification failed; inspect safe API/worker logs. No credentials printed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
