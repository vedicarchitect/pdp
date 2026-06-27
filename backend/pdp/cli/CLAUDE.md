# cli/ — Click CLI Entry Point

The `python -m pdp` command (`pdp.bat` / `pdp.ps1` wrappers at root).

## Files

| File | Purpose |
|------|---------|
| `core.py` | Root Click group, shared options |
| `strategy_commands.py` | `pdp strategy list/start/stop/status` |
| `backtest_commands.py` | `pdp backtest run/compare` |

## Usage

```powershell
# Via wrappers at repo root
.\pdp.bat strategy list
.\pdp.ps1 backtest run --date 2026-06-10

# Or directly
uv run python -m pdp strategy list
uv run python -m pdp backtest run --date 2026-06-10
```

## Convention

CLI commands are thin shells — all business logic stays in the relevant service module.
CLI reads env via `get_settings()`, never raw `os.getenv()`.
