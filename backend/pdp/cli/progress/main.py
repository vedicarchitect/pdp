from __future__ import annotations

import click
import structlog

from pdp.cli.progress.config import CLIConfig

log = structlog.get_logger()


@click.group()
def progress() -> None:
    """Progress testing commands - validate Dhan integration and portfolio engine."""


@progress.command("positions")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def positions_cmd(output_format: str) -> None:
    """Display current Dhan positions."""
    from pdp.cli.progress.commands.positions import show_positions

    config = CLIConfig.from_env()
    show_positions(config, output_format)


@progress.command("portfolio")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def portfolio_cmd(output_format: str) -> None:
    """Display portfolio summary."""
    from pdp.cli.progress.commands.portfolio import show_portfolio

    config = CLIConfig.from_env()
    show_portfolio(config, output_format)


@progress.command("option-chain")
@click.option("--symbol", default=None, help="Symbol to filter (default: NIFTY)")
@click.option("--expiry", default=None, help="Specific expiry (ISO YYYY-MM-DD); overrides --all-expiries")
@click.option("--all-expiries", is_flag=True, default=False, help="Show the nearest 3 expiries")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def option_chain_cmd(symbol: str | None, expiry: str | None, all_expiries: bool, output_format: str) -> None:
    """Fetch and display the option chain (nearest expiry by default)."""
    from pdp.cli.progress.commands.option_chain import show_option_chain

    config = CLIConfig.from_env()
    symbol = symbol or config.default_symbol
    show_option_chain(config, symbol, output_format, expiry=expiry, all_expiries=all_expiries)


@progress.command("greeks")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
def greeks_cmd(output_format: str) -> None:
    """Calculate and display Greeks for open positions."""
    from pdp.cli.progress.commands.greeks import show_greeks

    config = CLIConfig.from_env()
    show_greeks(config, output_format)
