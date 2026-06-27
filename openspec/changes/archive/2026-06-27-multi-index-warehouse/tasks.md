## Prerequisites

- `multi-index-options-backfill` MUST be implemented first — the gap-heal loop in `WarehouseService` calls `gap_backfill.backfill_gaps()` which must accept per-underlying params.
- BANKNIFTY and SENSEX expiry caches must exist (`data/expiry/banknifty_expiries.json`, `data/expiry/sensex_expiries.json`).

## 1. Settings

- [x] 1.1 Add `WAREHOUSE_UNDERLYINGS: list[str]` to `src/pdp/settings.py` (default `["NIFTY"]`)
- [x] 1.2 Define the static registry in `src/pdp/warehouse/service.py` (or a new `src/pdp/warehouse/config.py`):
  ```python
  UNDERLYING_REGISTRY: dict[str, dict] = {
      "NIFTY":     {"sid": "13", "step": 50,  "expiry_path_setting": "EXPIRY_CACHE_PATH"},
      "BANKNIFTY": {"sid": "25", "step": 100, "expiry_path_setting": "BANKNIFTY_EXPIRY_CACHE_PATH"},
      "SENSEX":    {"sid": "51", "step": 100, "expiry_path_setting": "SENSEX_EXPIRY_CACHE_PATH"},
  }
  ```
- [x] 1.3 Add startup validation: if any entry in `WAREHOUSE_UNDERLYINGS` is not in `UNDERLYING_REGISTRY`, raise `ValueError` before connecting to Dhan

## 2. Writer changes

- [x] 2.1 Remove `INDEX_SID` module-level constant from `src/pdp/warehouse/writer.py`
- [x] 2.2 `OptionBarWriter.__init__` accepts `underlying_cfg: dict` containing `sid`, `step`, and `underlying` name — used for bar tagging and subscription filtering
- [x] 2.3 Update all internal usages of the old `INDEX_SID` within `writer.py` to use `self._cfg["sid"]`

## 3. Service multi-underlying loop

- [x] 3.1 In `WarehouseService.__init__`, iterate over `settings.WAREHOUSE_UNDERLYINGS` and instantiate one `OptionBarWriter` per underlying, stored in `self._writers: dict[str, OptionBarWriter]` keyed by `security_id`
- [x] 3.2 Build the combined subscription list from all writers' ATM bands and pass to a single `DhanTickerAdapter` subscribe call (Dhan WS accepts multiple sids per call)
- [x] 3.3 In the tick-routing handler, look up the writer by incoming `security_id`; if `security_id` is not in `self._writers`, log a warning and skip (handles unsolicited ticks from Dhan)
- [x] 3.4 Band re-roll logic must run per underlying independently (each has its own ATM reference)

## 4. Gap-heal per underlying

- [x] 4.1 In the gap-heal loop, iterate over `self._writers` and call `backfill_gaps(underlying=..., underlying_sid=..., strike_step=...)` for each; guard with `try/except` so one underlying's failure does not block others
- [x] 4.2 If `multi-index-options-backfill` is not yet implemented, skip gap-heal for non-NIFTY underlyings and log a `warehouse.gap_heal.skipped` event with `reason="multi-index-options-backfill not implemented"`

## 5. Test updates

- [x] 5.1 In `tests/test_warehouse_feed.py`: remove `INDEX_SID` import; update test fixtures to pass `underlying_cfg` explicitly; confirm NIFTY-default behaviour unchanged
- [x] 5.2 Add a test: when `WAREHOUSE_UNDERLYINGS=["NIFTY","BANKNIFTY"]`, ticks for sid 25 are routed to the BANKNIFTY writer and produce docs with `underlying="BANKNIFTY"`
- [x] 5.3 Add a test: unsupported underlying in settings raises `ValueError` at startup

## 6. Documentation

- [x] 6.1 Update `src/pdp/warehouse/CLAUDE.md` — settings table (`WAREHOUSE_UNDERLYINGS`), remove `INDEX_SID` reference, update data-flow to show multi-underlying path
- [x] 6.2 Update root `CLAUDE.md` module index if any description changed

## 7. Validation & archive

- [x] 7.1 Start the warehouse locally with `WAREHOUSE_UNDERLYINGS=["NIFTY","BANKNIFTY"]` (paper mode); confirm both writers start without error
- [x] 7.2 Confirm `grep -r "INDEX_SID" src/ tests/` returns no matches
- [x] 7.3 `task test` and `task lint` / `task typecheck` green
- [x] 7.4 `openspec validate multi-index-warehouse --strict` passes
- [x] 7.5 Archive: `openspec archive multi-index-warehouse`
