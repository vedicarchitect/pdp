"""CLI for strategy lifecycle.

The strategy host runs inside the live API process, so these commands are a thin client
over the REST API (`/api/v1/strategies/...`) of a running PDP server — they do not spawn a
strategy standalone. Point at a different server with ``--api-url`` or ``PDP_API_URL``.
"""
from __future__ import annotations

import os

import click
import httpx

_DEFAULT_BASE = os.environ.get("PDP_API_URL", "http://localhost:8000")
_api_url_option = click.option(
    "--api-url", default=_DEFAULT_BASE, show_default=True, help="Base URL of the PDP API."
)


@click.group()
def strategy() -> None:
    """Strategy lifecycle commands (talk to a running PDP API)."""


def _get(api_url: str, path: str):
    try:
        with httpx.Client(base_url=api_url, timeout=10.0) as client:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(f"{exc.response.status_code}: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise click.ClickException(f"could not reach PDP API at {api_url}: {exc}") from exc


def _post(api_url: str, path: str):
    try:
        with httpx.Client(base_url=api_url, timeout=10.0) as client:
            resp = client.post(path)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(f"{exc.response.status_code}: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise click.ClickException(f"could not reach PDP API at {api_url}: {exc}") from exc


@strategy.command("list")
@_api_url_option
def list_strategies(api_url: str) -> None:
    """List registered strategies and their status."""
    data = _get(api_url, "/api/v1/strategies")
    if not data:
        click.echo("No strategies registered.")
        return
    for s in data:
        click.echo(f"{s['status']:<8} {s['id']}  (dropped_ticks={s.get('dropped_ticks', 0)})")


@strategy.command("start")
@click.argument("strategy_id")
@_api_url_option
def start_strategy(strategy_id: str, api_url: str) -> None:
    """Start a strategy by id."""
    result = _post(api_url, f"/api/v1/strategies/{strategy_id}/start")
    click.echo(f"started: {result}")


@strategy.command("stop")
@click.argument("strategy_id")
@_api_url_option
def stop_strategy(strategy_id: str, api_url: str) -> None:
    """Stop a running strategy by id."""
    result = _post(api_url, f"/api/v1/strategies/{strategy_id}/stop")
    click.echo(f"stopped: {result}")
