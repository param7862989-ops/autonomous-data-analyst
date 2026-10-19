"""Reject oversized request bodies before they are parsed or spooled to disk.

The declared ``Content-Length`` is checked first; the streamed body is also counted, so a
client that lies about (or omits) the length is cut off at the limit.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.request_context import get_request_id


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, limit_for: Callable[[str, str], int]) -> None:
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["method"], scope["path"])
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    await _send_413(send, limit)
                    return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await _send_413(send, limit)


async def _send_413(send: Send, limit: int) -> None:
    megabytes = limit / (1024 * 1024)
    readable = f"{megabytes:.0f} MB" if megabytes >= 1 else f"{limit // 1024} KB"
    body = json.dumps(
        {
            "error": {
                "code": "payload_too_large",
                "message": f"The request is larger than the {readable} limit.",
                "details": {"limit_bytes": limit},
                "request_id": get_request_id(),
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
