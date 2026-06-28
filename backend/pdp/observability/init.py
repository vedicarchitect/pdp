"""`python -m pdp.observability.init` — apply index templates + import dashboards.

Idempotent bootstrap for the unified log pipeline:
1. registers the composable index templates on OpenSearch (:9200), and
2. imports the dashboards-as-code saved objects (NDJSON under `infra/opensearch/dashboards/`)
   into OpenSearch Dashboards (:5601) via the saved-objects `_import` API.

Run via `task search:init`. Safe to re-run.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import structlog

from pdp.observability.client import close_opensearch, get_opensearch
from pdp.observability.mappings import ensure_templates
from pdp.settings import get_settings

log = structlog.get_logger("pdp.observability").bind(_no_ship=True)

# repo-root-relative when run from backend/ (cwd = backend)
_DASHBOARDS_DIR = Path("../infra/opensearch/dashboards")
_DASHBOARDS_URL = "http://localhost:5601"


async def _apply_templates() -> int:
    client = get_opensearch()
    if client is None:
        log.warning("opensearch_disabled", hint="set OPENSEARCH_ENABLED=true")
        return 0
    count = await ensure_templates(client, get_settings().OPENSEARCH_INDEX_PREFIX)
    await close_opensearch()
    return count


def _import_dashboards(dashboards_dir: Path = _DASHBOARDS_DIR, base_url: str = _DASHBOARDS_URL) -> int:
    if not dashboards_dir.exists():
        log.warning("dashboards_dir_missing", dir=str(dashboards_dir))
        return 0
    imported = 0
    url = f"{base_url}/api/saved_objects/_import?overwrite=true"
    for ndjson in sorted(dashboards_dir.glob("*.ndjson")):
        try:
            with httpx.Client(timeout=30.0) as http:
                resp = http.post(
                    url,
                    headers={"osd-xsrf": "true"},
                    files={"file": (ndjson.name, ndjson.read_bytes(), "application/ndjson")},
                )
            resp.raise_for_status()
            imported += 1
            log.info("dashboard_imported", file=ndjson.name)
        except Exception as exc:  # noqa: BLE001 — best-effort bootstrap
            log.warning("dashboard_import_failed", file=ndjson.name, exc=str(exc))
    return imported


def main() -> None:
    settings = get_settings()
    if not settings.OPENSEARCH_ENABLED:
        log.warning("opensearch_disabled", hint="set OPENSEARCH_ENABLED=true to init")
        return
    templates = asyncio.run(_apply_templates())
    dashboards = _import_dashboards()
    log.info("search_init_done", templates=templates, dashboards=dashboards)


if __name__ == "__main__":
    main()
