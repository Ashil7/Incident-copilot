"""Stable public errors; arbitrary exception details never enter responses."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.observability import request_id_context

CATALOG = {
    "QUEUE_UNAVAILABLE": (
        503,
        "Queue unavailable. Changes may already be saved; inspect the incident before retrying.",
    ),
    "INCIDENT_NOT_FOUND": (404, "Incident not found."),
    "FILE_NOT_FOUND": (404, "File not found."),
    "USER_NOT_FOUND": (404, "User not found."),
    "INVALID_CREDENTIALS": (401, "Invalid credentials or token."),
    "ADMIN_REQUIRED": (403, "Administrator access required."),
    "REGISTRATION_DISABLED": (403, "Public registration is disabled."),
    "ACCOUNT_EXISTS": (409, "Account already exists."),
    "ANALYSIS_ACTIVE": (409, "Files cannot change while analysis is queued or running."),
    "DATABASE_UNAVAILABLE": (503, "Database unavailable."),
    "STORAGE_UNAVAILABLE": (503, "Storage unavailable."),
    "SCHEMA_NOT_READY": (503, "Database schema is not current."),
}
DEFAULTS = {
    400: ("BAD_REQUEST", "Invalid request."),
    401: ("INVALID_CREDENTIALS", "Invalid credentials or token."),
    403: ("FORBIDDEN", "Access denied."),
    404: ("NOT_FOUND", "Resource not found."),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
    409: ("CONFLICT", "The operation conflicts with the current state."),
    413: ("UPLOAD_TOO_LARGE", "Upload exceeds the configured size limit."),
    422: ("VALIDATION_ERROR", "Invalid request data."),
    429: ("RATE_LIMITED", "Too many requests."),
    500: ("INTERNAL_ERROR", "An unexpected error occurred."),
    503: ("DEPENDENCY_UNAVAILABLE", "A required service is unavailable."),
}


class DomainError(HTTPException):
    def __init__(self, code):
        status, message = CATALOG[code]
        super().__init__(status, message)
        self.code = code


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_response(status: int, code: str | None = None, headers=None):
    default_code, default_message = DEFAULTS.get(
        status, ("HTTP_ERROR", "Request could not be completed.")
    )
    message = CATALOG[code][1] if code in CATALOG else default_message
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {
                "code": code or default_code,
                "message": message,
                "request_id": request_id_context.get(),
            }
        },
    )


async def http_error_handler(request: Request, error: HTTPException):
    code = getattr(error, "code", None)
    if code is None:
        # Transitional static domain messages; no unrecognized detail is returned.
        code = next(
            (key for key, value in CATALOG.items() if value == (error.status_code, error.detail)),
            None,
        )
    request.state.error_code = code or DEFAULTS.get(error.status_code, ("HTTP_ERROR", ""))[0]
    return error_response(error.status_code, code, error.headers)


async def validation_error_handler(request: Request, error: RequestValidationError):
    request.state.error_code = "VALIDATION_ERROR"
    return error_response(422)
