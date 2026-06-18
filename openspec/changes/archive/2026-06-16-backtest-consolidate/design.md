## Context

After the June 2026 strategy sweep, the codebase has three overlapping backtest entry points:
1. `backtest_multiday.py` (root, 1248 lines) — hardcoded ST(3,1)/5m monolith, now superseded
2. `scripts/backtest_sweep.py` — the active configurable sweep harness (sim.py + StrategyConfig)
3. `scripts/backtest_compare.py` — single-day backtest vs paper journal

`backtest_multiday.py` contains a full copy of the simulation logic that has since been factored into `src/pdp/backtest/sim.py`. The two scripts in `scripts/` are the right tools but live in the wrong place (mixed with data admin/migration scripts). There is no durable config format — running a specific strategy config requires passing raw JSON on the CLI or editing Python constants.

The promoted config (ST(10,2)/15m/OTM1) exists only as environment variables in `settings.py` and constants in `strategies/supertrend_short.yaml`. There is no machine-readable backtest config that ties the two together or can be posted to a future API endpoint.

## Goals / Non-Goals

**Goals:**
- Single obvious entry point: `backtest/run.py` (sweep + detail)
- Named, version-controlled configs: `backtest/configs/*.yaml`
- `StrategyConfig.from_yaml()` so configs can be loaded from disk or deserialized from a future API request body
- Clean Taskfile wiring: `task backtest` (per-trade detail, default config) and `task backtest:sweep` (grid)
- `backtest/CLAUDE.md` so a new session knows exactly what lives where

**Non-Goals:**
- No changes to `sim.py`, `day_loader.py`, or `commissions.py` (simulation logic is correct)
- No API endpoint yet (frontend seam is shape compatibility only)
- No UI changes
- No changes to paper/live strategy (`supertrend_short.py`, `supertrend_short.yaml`)

## Decisions

### D1: Top-level `backtest/` folder, not `src/pdp/backtest/`

`src/pdp/backtest/` is the Python package (importable modules). The new `backtest/` folder holds runnable scripts and config YAML — neither belongs in the package. This mirrors how `strategies/` holds YAML at root while `src/pdp/strategies/` holds the Python implementations.

**Alternative considered:** Put scripts inside the package as `src/pdp/backtest/cli/`. Rejected because scripts have `sys.path.insert` hacks and direct `if __name__ == "__main__"` blocks that don't belong in importable modules.

### D2: YAML shape mirrors `StrategyConfig.to_dict()` exactly

The YAML config is just `StrategyConfig.to_dict()` serialized to a file. `from_yaml(path)` reads it and calls `from_dict(data)`. No separate YAML schema.

**Why:** Zero divergence between JSON API payloads, YAML files, and the Python dataclass. One conversion path, tested once.

### D3: `task backtest` runs single-config detail for the default config

Default config is `BACKTEST_DEFAULT_CONFIG` (settings) pointing to `backtest/configs/st10_15m_otm1.yaml`. This gives a per-trade view of the last 7 days for the active strategy — the most common "what happened" query.

**Alternative:** `task backtest` runs the grid. Rejected because the grid takes 2-3 minutes; the quick sanity check should be fast (< 30s for 7 days).

### D4: Archive, don't delete, `backtest_multiday.py`

The file remains readable in `scripts/archive/` as a reference for the original simulation semantics. It is no longer referenced from Taskfile or RUNBOOK.

## Risks / Trade-offs

- **Risk: Scripts import via `sys.path.insert`** — Moving scripts to `backtest/` means the insert path becomes `../src` instead of `src`. This is a one-line fix but easy to miss.
  → Mitigation: tasks.md explicitly calls this out.

- **Risk: `BACKTEST_DEFAULT_CONFIG` not set** — If the env var is missing, `task backtest` must degrade gracefully (fall back to the hardcoded promoted config, not crash).
  → Mitigation: settings default = `"backtest/configs/st10_15m_otm1.yaml"`.

- **Risk: `backtest_compare.py` uses hardcoded `scripts/` imports** — It has its own `sys.path.insert` pointing to `../src`. Relocating it to `backtest/` requires a path fix.
  → Mitigation: straightforward; flagged in tasks.md.

## Migration Plan

1. Create `backtest/` folder + `configs/` subfolder
2. Create YAML configs (st10_15m_otm1, st3_1_5m_otm1 baseline anchor)
3. Add `StrategyConfig.from_yaml()` + `to_yaml()` to `strategy_config.py`
4. Copy (not move yet) `scripts/backtest_sweep.py` to `backtest/run.py`, fix sys.path, add `--config-file` flag
5. Copy `scripts/backtest_compare.py` to `backtest/compare.py`, fix sys.path
6. Update Taskfile to point at new locations
7. Verify tests still pass
8. Archive `backtest_multiday.py` → `scripts/archive/`
9. Remove old scripts from `scripts/` (or keep as thin shims for one release)
10. Create `backtest/CLAUDE.md`
11. Update root `CLAUDE.md` + RUNBOOK

Rollback: All old files remain in `scripts/archive/` and `scripts/`; revert Taskfile entries.

## Open Questions

- Should `backtest/compare.py` also gain a `--config-file` flag (so it uses the same YAML), or keep it standalone? (Current plan: keep standalone; it compares to paper journal and doesn't need the full StrategyConfig.)
- Should `backtest/configs/` be gitignored for user-local experiments, or always committed? (Current plan: always committed — configs are the "what we ran" record.)
