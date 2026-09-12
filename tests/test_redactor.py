"""Synthetic secret coverage for independently callable masking rules."""

import json

import pytest

from app.services.redactor import MASK, redact_json, redact_text


@pytest.mark.parametrize(
    "text,secret",
    [
        ("Authorization: Bearer abc.def", "abc.def"),
        ("Authorization: Basic ZGVtbzpwYXNz", "ZGVtbzpwYXNz"),
        ('password="two word secret"', "two word secret"),
        ("password: demo", "demo"),
        ("api_key=demo", "demo"),
        ("apikey: demo", "demo"),
        ("secret=demo", "demo"),
        ("access_token=demo", "demo"),
        ("session_id=demo", "demo"),
        ("Cookie: session=demo; tracking=other", "other"),
        ("demo@example.invalid", "demo@example.invalid"),
        ("card=4111-1111-1111-1111", "4111"),
        ("phone=+1-202-555-0123", "555"),
        ("/api?token=demo%20secret&ok=yes", "demo"),
        ('{"password":"demo", broken', "demo"),
    ],
)
def test_redacts_known_values(text: str, secret: str) -> None:
    result = redact_text(text)
    assert secret not in result
    assert MASK in result


def test_nested_json_secrets_and_numeric_accounts() -> None:
    data = {
        "nested": [{"apiKey": "synthetic-secret", "account": 123456789012}],
        "message": "email demo@example.invalid",
    }
    safe = json.dumps(redact_json(data))
    for secret in ("synthetic-secret", "123456789012", "demo@example.invalid"):
        assert secret not in safe
    assert data["nested"][0]["apiKey"] == "synthetic-secret"


def test_optional_ip_redaction_and_timestamp_preservation() -> None:
    text = "2026-09-11T12:34:56Z INFO 192.0.2.1 500 25ms"
    assert redact_text(text) == text
    safe = redact_text(text, mask_ipv4=True)
    assert "192.0.2.1" not in safe
    assert "2026-09-11T12:34:56Z" in safe


def test_redaction_is_idempotent() -> None:
    safe = redact_text("password=demo Authorization: Bearer abc.def")
    assert redact_text(safe) == safe
