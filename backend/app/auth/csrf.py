"""CSRF protection for cookie-authenticated, state-changing API requests.

Three independent checks on POST/PUT/PATCH/DELETE under /api:

1. ``X-Requested-With: fetch`` must be present. A cross-site HTML form cannot set custom
   headers, and a cross-site ``fetch`` that sets one triggers a CORS preflight the API rejects.
2. If the browser sends ``Sec-Fetch-Site``, it must not be ``cross-site``.
3. If the browser sends ``Origin``, it must be one of the configured frontend origins.

The session cookie is also ``SameSite=Lax``, which on its own blocks cross-site POSTs in
modern browsers. These checks do not rely on that.
"""

from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.request_context import get_request_id

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "fetch"


class CSRFMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str], path_prefix: str) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in UNSAFE_METHODS
            and scope["path"].startswith(self.path_prefix)
        ):
            reason = self._rejection_reason(Headers(scope=scope))
            if reason is not None:
                await _forbidden(send, reason)
                return
        await self.app(scope, receive, send)

    def _rejection_reason(self, headers: Headers) -> str | None:
        if headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
            return "missing_header"
        if headers.get("sec-fetch-site") == "cross-site":
            return "cross_site"
        origin = headers.get("origin")
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            return "origin_not_allowed"
        return None


async def _forbidden(send: Send, reason: str) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "csrf_failed",
                "message": "The request was blocked by cross-site request protection.",
                "details": {"reason": reason},
                "request_id": get_request_id(),
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
