# Tasks

## 1. Fix

- [x] 1.1 Remove `family: vwap` from the index-sid watchlist entry in
      `backend/strategies/directional_strangle_nifty.yaml`
- [x] 1.2 Remove `family: vwap` from the index-sid watchlist entry in
      `backend/strategies/directional_strangle_banknifty.yaml`
- [x] 1.3 Remove `family: vwap` from the index-sid watchlist entry in
      `backend/strategies/directional_strangle_sensex.yaml`
- [x] 1.4 Add a short comment at each removed line (or a note in
      `backend/strategies/CLAUDE.md`) recording why VWAP is absent and the re-enable
      condition (futures `market_bars` history required for backtest parity)

## 2. Verify

- [x] 2.1 `openspec validate --strict strangle-drop-unused-vwap-watchlist`
- [x] 2.2 Live/boot smoke: restarted `dev:trade` 2026-07-20 ~10:56 IST. `Indicators` readiness
      went `ok` for all three strangles immediately after the first live 5m bar closed;
      `Bias`/`Chain` also `ok` (Dhan token was refreshed same session). Full readiness `state:
      ok` confirmed for NIFTY/BANKNIFTY/SENSEX — first time all 5 components green this session.
      Live paper entries fired within the same minute for all three (NIFTY: PE24100/CE24300
      shorts + PE23100/CE25200 hedges; SENSEX: CE77800/PE77500/CE77900 shorts + 3 hedges;
      BANKNIFTY entered and bucket transitioned neutral→more_bear intra-session) — the
      multi-week zero-paper-trade drought is resolved as of this restart.
- [x] 2.3 `task test`: 1206 passed, 3 failed — all 3 confined to
      `tests/observability/test_processor.py` (OpenSearch indexer queue-size assertions,
      unrelated to watchlists/strategies/indicators). Re-ran that file alone twice, both
      clean (7 passed) — confirmed pre-existing test-isolation flakiness, not a regression
      from this change.

## 3. Archive

- [ ] 3.1 `openspec archive strangle-drop-unused-vwap-watchlist` once 2.2 passes on a live
      market day
