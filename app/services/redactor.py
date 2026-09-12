"""Conservative synthetic-log redaction; not a guarantee that every secret is removed."""

import ipaddress
import re
from typing import Any

MASK = "[REDACTED]"
SENSITIVE_KEYS = {
    "authorization",
    "password",
    "passwd",
    "pwd",
    "secret",
    "clientsecret",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "session",
    "sessionid",
    "cookie",
    "setcookie",
    "traceid",
    "correlationid",
}
KEY_PATTERN = (
    r"authorization|password|passwd|pwd|secret|client[_-]?secret|"
    r"(?:access[_-]?|refresh[_-]?)?token|api[_-]?key|session(?:[_-]?id)?|"
    r"set-cookie|cookie|trace[_-]?id|correlation[_-]?id"
)
AUTH = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
COOKIES = re.compile(r"\b(?:set-cookie|cookie)\s*[:=]\s*[^\r\n]+", re.IGNORECASE)
FIELDS = re.compile(
    rf"(?<![\w-])(?P<key>{KEY_PATTERN})(?P<sep>[\"']?\s*[:=]\s*)"
    r"(?P<value>\[REDACTED\]|\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s&,;\}\]]+)",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
LONG_NUMBER = re.compile(r"(?<![\w])(?:\d[ -]?){11,18}\d(?!\w)")
# Deliberately avoid ISO date patterns: phone groups use 3-3-4 digits.
PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\w)")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")


def sensitive_key(key: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", key.lower()) in SENSITIVE_KEYS


def redact_authorization(text: str) -> str:
    return AUTH.sub(lambda match: f"{match.group(1)} {MASK}", text)


def redact_fields(text: str) -> str:
    text = COOKIES.sub(f"cookie={MASK}", text)
    return FIELDS.sub(lambda match: f"{match.group('key')}{match.group('sep')}{MASK}", text)


def redact_emails(text: str) -> str:
    return EMAIL.sub(MASK, text)


def redact_numbers(text: str) -> str:
    return PHONE.sub(MASK, LONG_NUMBER.sub(MASK, text))


def redact_ipv4(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            ipaddress.IPv4Address(match.group())
        except ipaddress.AddressValueError:
            return match.group()
        return MASK

    return IPV4.sub(replace, text)


def redact_text(text: str, *, mask_ipv4: bool = False) -> str:
    """Mask known secret assignments (including URL queries), PII, and optional IPv4."""
    text = redact_fields(redact_authorization(text))
    text = redact_numbers(redact_emails(text))
    return redact_ipv4(text) if mask_ipv4 else text


def redact_json(value: Any, *, mask_ipv4: bool = False) -> Any:
    """Mask structured secret values before serializing or extracting event fields."""
    if isinstance(value, dict):
        return {
            redact_text(str(key), mask_ipv4=mask_ipv4): (
                MASK if sensitive_key(str(key)) else redact_json(item, mask_ipv4=mask_ipv4)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item, mask_ipv4=mask_ipv4) for item in value]
    if isinstance(value, str):
        return redact_text(value, mask_ipv4=mask_ipv4)
    # Numeric account-like JSON values must not bypass text masking.
    if isinstance(value, int) and not isinstance(value, bool) and 12 <= len(str(abs(value))) <= 19:
        return MASK
    return value
