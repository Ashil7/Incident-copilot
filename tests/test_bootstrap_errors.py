"""Setup diagnostics must identify errors without echoing credentials."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.auth_schemas import RegisterRequest
from scripts.bootstrap_admin import BootstrapError, failure_reason


def test_short_password_diagnostic_does_not_echo_input():
    with pytest.raises(ValidationError) as error:
        RegisterRequest(email="admin@example.com", full_name="Admin", password="private")
    message = failure_reason(error.value)
    assert message == "Password must contain 12–128 characters."
    assert "private" not in message


def test_database_diagnostic_omits_driver_details():
    error = OperationalError("private SQL", {}, SimpleNamespace(sqlstate="42501"))
    assert failure_reason(error) == "The database role lacks permission for this operation."
    assert (
        failure_reason(RuntimeError("private password"))
        == "Unexpected setup failure; no credentials printed."
    )


def test_controlled_duplicate_message():
    assert (
        failure_reason(BootstrapError("Email already exists; no account was changed."))
        == "Email already exists; no account was changed."
    )
