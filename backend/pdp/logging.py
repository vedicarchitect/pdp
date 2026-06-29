from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# Patterns for secret-shaped values — redacted to "***" in all sinks.
_REDACT_KEY_RE = re.compile(
    r"(access[_-]?token|api[_-]?key|password|bearer)",
    re.IGNORECASE,
)
_REDACT_JWT_RE = re.compile(r"eyJ[\w.\-]{20,}")

_REDACT_MARKER = "***"


def _redact_value(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    if _REDACT_JWT_RE.search(v):
        return _REDACT_MARKER
    return v


def sensitive_data_filter(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: redact secret-shaped keys/values from every record."""
    for key in list(event_dict.keys()):
        if _REDACT_KEY_RE.search(key):
            event_dict[key] = _REDACT_MARKER
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


class _ErrorsJsonlSink:
    """Structlog processor that appends ERROR-level records as JSONL; no-op below ERROR."""

    def __init__(self, path: str, max_lines: int) -> None:
        self._path = Path(path)
        self._max_lines = max_lines

    def truncate_on_startup(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines(keepends=True)
            if len(lines) > self._max_lines:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(
                    "".join(lines[-self._max_lines :]), encoding="utf-8"
                )
        except OSError:
            pass

    def __call__(
        self, logger: Any, method: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        level = event_dict.get("level", "").upper()
        if level != "ERROR":
            return event_dict
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event_dict, default=str) + "\n")
        except OSError:
            # Never break request handling on write failure — swallow and warn once
            try:
                logging.getLogger(__name__).warning(
                    "errors_jsonl_write_failed", extra={"path": str(self._path)}
                )
            except Exception:
                pass
        return event_dict


# Module-level singletons set by configure_logging(); None until then.
_errors_sink: _ErrorsJsonlSink | None = None


def truncate_errors_jsonl() -> None:
    """Called from main.py lifespan startup to trim the error log file."""
    if _errors_sink is not None:
        _errors_sink.truncate_on_startup()


def configure_logging(level: str = "INFO", *, redaction_enabled: bool = True,
                      errors_jsonl_path: str = "logs/errors.jsonl",
                      errors_jsonl_max_lines: int = 1000) -> None:
    global _errors_sink
    from pdp.observability.processor import opensearch_sink

    errors_sink = _ErrorsJsonlSink(errors_jsonl_path, errors_jsonl_max_lines)
    _errors_sink = errors_sink

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if redaction_enabled:
        processors.append(sensitive_data_filter)

    processors += [
        # errors.jsonl sink — ERROR-only, additive (runs before OpenSearch + JSON)
        errors_sink,
        # Tier-A: ship every record to OpenSearch (no-op until the indexer is active).
        opensearch_sink,
        structlog.processors.JSONRenderer(),
    ]

    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        cache_logger_on_first_use=True,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # `source=api` segregates request-path logs from background-service logs in pdp-logs-*.
        structlog.contextvars.bind_contextvars(request_id=request_id, source="api")
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
