"""Pure ASGI middleware: request ids and security headers."""

from __future__ import annotations

import json
import logging
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.request_context import reset_request_id, set_request_id

logger = logging.getLogger(__name__)

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# API responses are JSON; nothing should ever execute or be framed from them.
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


class RequestContextMiddleware:
    """Assigns a request id, exposes it as ``X-Request-ID`` and applies security headers.

    It also converts unexpected exceptions into the sanitized 500 envelope. Doing this here
    (rather than in an ``Exception`` handler, which Starlette runs in the outermost
    ``ServerErrorMiddleware``) keeps the request id and security headers on 500 responses.
    """

    def __init__(self, app: ASGIApp, *, docs_paths: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.docs_paths = docs_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = set_request_id(request_id)
        path: str = scope.get("path", "")
        is_docs = path in self.docs_paths

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", _API_CSP)
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method"), path)
            if response_started:
                raise
            await _send_internal_error(send_wrapper, request_id)
        finally:
            reset_request_id(token)


async def _send_internal_error(send: Send, request_id: str) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "details": None,
                "request_id": request_id,
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
