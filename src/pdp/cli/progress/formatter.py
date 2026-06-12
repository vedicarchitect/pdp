from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    Console = None
    Table = None


console = Console() if Console else None


def print_table(title: str, headers: list[str], rows: list[list[str]], format_type: str = "table") -> None:
    if format_type == "json":
        json_data = [dict(zip(headers, row)) for row in rows]
        print(json.dumps(json_data, indent=2))
    elif console:
        table = Table(title=title)
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*row)
        console.print(table)
    else:
        print(f"\n{title}")
        print(" | ".join(headers))
        print("-" * (sum(len(h) for h in headers) + 3 * len(headers)))
        for row in rows:
            print(" | ".join(row))


def format_timestamp(ts: datetime | None = None) -> str:
    if ts is None:
        ts = datetime.now(tz=_IST)
    return ts.isoformat()


def format_number(value: float | None, decimal_places: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimal_places}f}"


def print_message(message: str, error: bool = False) -> None:
    if console:
        if error:
            console.print(f"[bold red]{message}[/bold red]")
        else:
            console.print(f"[bold]{message}[/bold]")
    else:
        print(message)
