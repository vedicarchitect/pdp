"""Async OpenSearch client singleton, env-configured via `get_settings()`.

Returns ``None`` when `OPENSEARCH_ENABLED` is false so the whole pipeline is inert with no
connection attempts. The URL is the only thing that changes between local compose and AWS
OpenSearch Service (chunk 16).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from pdp.settings import get_settings

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch

# Bound `_no_ship` so the pipeline's own logs are never re-shipped (no feedback loop).
log = structlog.get_logger("pdp.observability").bind(_no_ship=True)

_client: AsyncOpenSearch | None = None


def get_opensearch() -> AsyncOpenSearch | None:
    """Return the shared async client, or ``None`` when disabled."""
    global _client
    settings = get_settings()
    if not settings.OPENSEARCH_ENABLED:
        return None
    if _client is None:
        from opensearchpy import AsyncOpenSearch

        http_auth = (
            (settings.OPENSEARCH_USER, settings.OPENSEARCH_PASSWORD)
            if settings.OPENSEARCH_USER
            else None
        )
        _client = AsyncOpenSearch(
            hosts=[settings.OPENSEARCH_URL],
            http_auth=http_auth,
            verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
            ssl_show_warn=False,
        )
        log.info("opensearch_client_created", url=settings.OPENSEARCH_URL)
    return _client


async def close_opensearch() -> None:
    """Close and reset the shared client (lifespan shutdown / tests)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
