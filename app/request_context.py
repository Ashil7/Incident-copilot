"""Pure ASGI middleware preserves context through synchronous background tasks."""

import logging
from time import monotonic
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders

from app.errors import error_response
from app.observability import log_event, request_id_context


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        token = request_id_context.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        start = monotonic()
        started = finished = False
        status = 500

        def fields():
            method = scope.get("method")
            return {
                "route": getattr(scope.get("route"), "path", "unmatched"),
                "method": method
                if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                else "OTHER",
                "status_code": status,
                "duration_ms": round((monotonic() - start) * 1000, 3),
                "user_id": scope["state"].get("user_id"),
                "error_code": scope["state"].get("error_code"),
            }

        async def send_response(message):
            nonlocal started, finished, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
                headers["Pragma"] = "no-cache"
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
                log_event("request.completed", **fields())

        try:
            await self.app(scope, receive, send_response)
        except Exception as error:
            code = (
                "DEPENDENCY_UNAVAILABLE" if isinstance(error, SQLAlchemyError) else "INTERNAL_ERROR"
            )
            if not started:
                status = 503 if isinstance(error, SQLAlchemyError) else 500
            scope["state"]["error_code"] = code
            log_event(
                "background.failed" if started else "request.failed",
                level=logging.ERROR,
                **fields(),
                error_type=type(error).__name__,
            )
            if not started:
                response = error_response(503 if isinstance(error, SQLAlchemyError) else 500)
                await response(scope, receive, send_response)
            elif not finished:
                await send_response({"type": "http.response.body", "body": b"", "more_body": False})
            # Do not forward arbitrary exception text to Uvicorn's traceback logger.
        finally:
            request_id_context.reset(token)
