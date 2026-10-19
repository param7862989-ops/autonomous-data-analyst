"""Logging setup. Log lines carry the request id; request bodies and secrets are never logged."""

from __future__ import annotations

import logging

from app.request_context import get_request_id


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    # Replace handlers so repeated app creation (tests, reload) does not duplicate output.
    root.handlers = [handler]
    root.setLevel(level)
    # Third-party HTTP client debug logs can include headers; keep them quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, logging.getLevelName(level)))
