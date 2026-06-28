"""Unified OpenSearch log pipeline (trade-analysis-feedback-loop capability).

Every backend `structlog` record + Flutter UI log auto-ships to OpenSearch in realtime
through a single non-blocking ``OpenSearchIndexer``, segregated by a ``source`` field.
High-value events also route to strict-mapped typed analytics indices. JSONL/Mongo remain
the source of truth; OpenSearch is the derived, queryable, realtime layer.
"""
from __future__ import annotations

from pdp.observability.client import close_opensearch, get_opensearch
from pdp.observability.indexer import (
    OpenSearchIndexer,
    get_active_indexer,
    set_active_indexer,
)

__all__ = [
    "OpenSearchIndexer",
    "close_opensearch",
    "get_active_indexer",
    "get_opensearch",
    "set_active_indexer",
]
