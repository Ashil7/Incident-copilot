"""Authentication contracts, credential privacy, and refresh-token lifecycle."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.models import RefreshToken, User
from app.services import auth

ACCOUNT = {
    "email": "analyst@example.com",
    "password": "Synthetic-password-123!",
    "full_name": "Demo Analyst",
}


def register(client):
    response = client.post("/api/v1/auth/register", json=ACCOUNT)
    assert response.status_code == 201
    return response.json()


def login(client):
    response = client.post(
        "/api/v1/auth/login", json={key: ACCOUNT[key] for key in ("email", "password")}
    )
    assert response.status_code == 200
    return response.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_login_me_rotation_and_logout(client):
    user = register(client)
    assert user["role"] == "ANALYST"
    assert set(user) == {"id", "email", "full_name", "role", "is_active"}
    tokens = login(client)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 900
    response = client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert response.json() == user
    assert response.headers["cache-control"] == "no-store"
    with client.app.state.session_factory() as session:
        stored = session.get(User, user["id"])
        assert stored.password_hash.startswith("$argon2id$")
        assert ACCOUNT["password"] not in stored.password_hash
        row = session.scalar(select(RefreshToken))
        assert row.token_hash == auth.token_hash(tokens["refresh_token"])
        assert row.token_hash != tokens["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )
    current = rotated.json()
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": current["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": current["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": current["refresh_token"]}
        ).status_code
        == 401
    )
    # Logout revokes the supplied refresh token; issued access tokens expire naturally.
    assert client.get("/api/v1/auth/me", headers=bearer(current["access_token"])).status_code == 200


def test_normalized_email_duplicates_and_registration_toggle(client):
    payload = {**ACCOUNT, "email": " ANALYST@EXAMPLE.COM "}
    assert client.post("/api/v1/auth/register", json=payload).json()["email"] == ACCOUNT["email"]
    assert client.post("/api/v1/auth/register", json=ACCOUNT).status_code == 409
    client.app.state.settings.allow_registration = False
    assert (
        client.post(
            "/api/v1/auth/register", json={**ACCOUNT, "email": "other@example.com"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "change",
    [
        {"role": "ADMIN"},
        {"is_active": True},
        {"password": "tiny-secret"},
        {"email": "invalid-email"},
        {"full_name": " "},
    ],
)
def test_registration_validation_never_echoes_secrets(client, change):
    response = client.post("/api/v1/auth/register", json={**ACCOUNT, **change})
    assert response.status_code == 422
    assert ACCOUNT["password"] not in response.text
    assert "tiny-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"
    with client.app.state.session_factory() as session:
        assert session.scalar(select(User)) is None


def test_wrong_password_and_unknown_user_same_error(client):
    register(client)
    wrong = client.post("/api/v1/auth/login", json={"email": ACCOUNT["email"], "password": "wrong"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "mutation",
    [
        "expired",
        "wrong_key",
        "wrong_type",
        "wrong_issuer",
        "wrong_audience",
        "missing_exp",
        "none_algorithm",
    ],
)
def test_invalid_access_tokens_rejected(client, mutation):
    register(client)
    tokens = login(client)
    settings = client.app.state.settings
    key = settings.jwt_secret_key.get_secret_value()
    claims = jwt.decode(
        tokens["access_token"], key, algorithms=["HS256"], audience=settings.jwt_audience
    )
    algorithm = "HS256"
    if mutation == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif mutation == "wrong_key":
        key = "different-test-signing-key-32-bytes-long"
    elif mutation == "wrong_type":
        claims["type"] = "refresh"
    elif mutation == "wrong_issuer":
        claims["iss"] = "other"
    elif mutation == "wrong_audience":
        claims["aud"] = "other"
    elif mutation == "missing_exp":
        del claims["exp"]
    else:
        key, algorithm = None, "none"
    token = jwt.encode(claims, key, algorithm=algorithm)
    response = client.get("/api/v1/auth/me", headers=bearer(token))
    assert response.status_code == 401
    assert token not in response.text


def test_inactive_user_denied_login_me_and_refresh(client):
    user = register(client)
    tokens = login(client)
    with client.app.state.session_factory() as session:
        session.execute(update(User).where(User.id == user["id"]).values(is_active=False))
        session.commit()
    assert client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"])).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={key: ACCOUNT[key] for key in ("email", "password")}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_expired_refresh_and_token_type_separation(client):
    register(client)
    tokens = login(client)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(tokens["refresh_token"])).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        ).status_code
        == 401
    )
    with client.app.state.session_factory() as session:
        session.execute(
            update(RefreshToken).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        )
        session.commit()
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_refresh_rollback_keeps_old_token_usable(client, monkeypatch):
    register(client)
    tokens = login(client)
    original = auth.issue_tokens

    def unavailable(*args):
        raise OperationalError("synthetic", {}, Exception("private-db-secret"))

    monkeypatch.setattr(auth, "issue_tokens", unavailable)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 503
    assert "private-db-secret" not in response.text
    monkeypatch.setattr(auth, "issue_tokens", original)
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("key", ["", "too-short"])
def test_missing_or_short_signing_key_is_rejected(key):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, jwt_secret_key=key).validate_auth_configuration()


def test_registration_disabled_by_default_and_production_debug_rejected():
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=True,
        jwt_secret_key="synthetic-test-signing-key-32-bytes",
    )
    assert settings.allow_registration is False
    with pytest.raises(RuntimeError, match="DEBUG"):
        settings.validate_auth_configuration()


def test_smoke_script_keeps_credentials_out_of_output(client, capsys):
    from scripts.verify_auth import verify

    verify(client)
    output = capsys.readouterr().out
    assert "PASS:" in output
    assert "access_token" not in output
    assert "refresh_token" not in output
    assert "$argon2" not in output
