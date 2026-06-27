"""Read-only Dhan account client for broker sync.

Wraps the synchronous ``dhanhq`` SDK report methods behind a small async interface, reusing the
same credential bootstrapping as :class:`pdp.orders.dhan_broker.DhanBroker`. All calls are
read-only (no orders). Blocking SDK calls run in a worker thread. The SDK envelope
``{"status", "remarks", "data"}`` is unwrapped here; a ``failure`` raises ``BrokerSyncError``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pdp.settings import Settings

log = structlog.get_logger()


class BrokerSyncError(RuntimeError):
    """Raised when a Dhan read API returns a failure envelope."""


class BrokerAccountClient:
    """Async, read-only accessor for Dhan account reports."""

    def __init__(self, settings: Settings) -> None:
        self._client_id = settings.DHAN_CLIENT_ID
        self._access_token = settings.DHAN_ACCESS_TOKEN
        self._client: Any = None

    @property
    def account_id(self) -> str:
        return self._client_id

    @property
    def has_credentials(self) -> bool:
        return bool(self._client_id and self._access_token)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from dhanhq import DhanContext, dhanhq

            self._client = dhanhq(DhanContext(self._client_id, self._access_token))
        return self._client

    async def _call(self, method_name: str, /, **kwargs: Any) -> Any:
        """Run a sync SDK method in a thread and unwrap the response envelope."""

        def _invoke() -> Any:
            client = self._ensure_client()
            fn = getattr(client, method_name)
            return fn(**kwargs)

        resp = await asyncio.to_thread(_invoke)
        if isinstance(resp, dict):
            if resp.get("status") == "failure":
                raise BrokerSyncError(f"{method_name}: {resp.get('remarks')}")
            return resp.get("data", resp)
        return resp

    @staticmethod
    def _as_rows(data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    # ── State reports (point-in-time) ──────────────────────────────────────────
    async def fetch_holdings(self) -> list[dict[str, Any]]:
        return self._as_rows(await self._call("get_holdings"))

    async def fetch_positions(self) -> list[dict[str, Any]]:
        return self._as_rows(await self._call("get_positions"))

    async def fetch_funds(self) -> list[dict[str, Any]]:
        return self._as_rows(await self._call("get_fund_limits"))

    # ── Transactional reports (per day / range) ────────────────────────────────
    async def fetch_orders(self) -> list[dict[str, Any]]:
        return self._as_rows(await self._call("get_order_list"))

    async def fetch_trades(self) -> list[dict[str, Any]]:
        return self._as_rows(await self._call("get_trade_book"))

    async def fetch_trade_history(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 0
        while True:
            data = await self._call(
                "get_trade_history", from_date=from_date, to_date=to_date, page_number=page
            )
            batch = self._as_rows(data)
            if not batch:
                break
            rows.extend(batch)
            page += 1
            if page > 200:  # safety bound
                break
        return rows

    async def fetch_ledger(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        return self._as_rows(
            await self._call("ledger_report", from_date=from_date, to_date=to_date)
        )
