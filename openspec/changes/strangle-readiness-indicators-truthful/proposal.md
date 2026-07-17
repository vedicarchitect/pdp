# strangle-readiness-indicators-truthful

## Why

`strangle-observability-gaps` specified that an unseeded indicator MUST block a strategy's readiness
("An unseeded indicator blocks readiness"). The implementation silently never did.

`DirectionalStrangle.check_readiness` built the Indicators component by calling
`self.ctx.indicators.seeding_summary(self.underlying, tf)` — passing the underlying **name**
(`"NIFTY"`). But `IndicatorEngine` keys its suites by **security_id** (`"13"`), so
`seeding_summary("NIFTY", tf)` always returns `{}`. With an empty summary the component reported
`ok` on every bar, regardless of whether EMA(200) or any other configured indicator had actually
converged. The readiness gate meant to protect against trading on unconverged indicators was a
no-op — a monitoring blind spot that made the Execution Console's readiness chip lie.

This was found during the 2026-07-17 paper-trading investigation, alongside the entry-fill race
(`strangle-entry-fill-race-and-latch`) and the recurring warmup gap
(`indicator-warmup-derive-from-1m`).

## What Changes

- `check_readiness` keys the Indicators component by `self.sid` (the security_id the engine uses),
  so an unseeded indicator on `5m`/`15m`/`1H`/`1w` now actually surfaces as `blocked` with the
  family/period/timeframe in the reason — honoring the existing spec scenario for real.
- Add a regression test asserting `seeding_summary` is consulted with the security_id, not the
  underlying name, and that an unseeded indicator keyed by that sid blocks readiness.

Note: this makes the readiness gate genuinely enforcing. Combined with
`indicator-warmup-derive-from-1m` (which closes the EMA-depth gap from the complete 1m series), a
correctly-seeded strategy stays `ok`; a genuinely unconverged one is now correctly held out of new
entries (existing positions continue to be managed, per the unchanged blocking-behavior requirement).

## Impact

- Affected specs: `strangle-observability-gaps` (sharpen the readiness requirement to specify keying
  by security_id).
- Affected code: `backend/pdp/strategies/directional_strangle.py::check_readiness` (one-line keying
  fix + comment). No schema/migration changes.
