"""Local HTTP auth smoke test; passwords and tokens remain only in memory."""

import argparse
import secrets
from uuid import uuid4

import httpx


def verify(client: httpx.Client) -> None:
    email = f"smoke-{uuid4().hex}@example.com"
    password = secrets.token_urlsafe(32)

    def check(response: httpx.Response, expected: int, stage: str) -> dict:
        if response.status_code != expected:
            raise RuntimeError(
                f"{stage}: expected HTTP {expected}, received {response.status_code}."
            )
        if response.headers.get("cache-control") != "no-store":
            raise RuntimeError(f"{stage}: missing no-store header.")
        return response.json() if expected != 204 else {}

    account = check(
        client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "full_name": "Synthetic auth smoke test",
            },
        ),
        201,
        "registration",
    )
    tokens = check(
        client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200, "login"
    )
    user = check(
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
        ),
        200,
        "me",
    )
    if user != account or user.get("role") != "ANALYST":
        raise RuntimeError("Unexpected account response.")
    rotated = check(
        client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}),
        200,
        "refresh",
    )
    check(
        client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}),
        401,
        "old refresh rejection",
    )
    check(
        client.post("/api/v1/auth/logout", json={"refresh_token": rotated["refresh_token"]}),
        204,
        "logout",
    )
    check(
        client.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}),
        401,
        "revoked refresh rejection",
    )
    print(
        "PASS: registration, login, me, refresh rotation, replay rejection, logout; no credentials printed."
    )
    print("A synthetic ANALYST account remains in the database:", email)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}", timeout=20, trust_env=False
        ) as client:
            verify(client)
    except RuntimeError as error:
        print(str(error))  # Only the controlled stage/status messages above.
        raise SystemExit(1) from None
    except Exception:
        print(
            "Authentication smoke test failed. Check local API availability; no credentials printed."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
