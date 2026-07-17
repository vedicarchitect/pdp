# Tasks — strangle-readiness-indicators-truthful

## 1. Fix the keying
- [x] 1.1 `check_readiness` Indicators component: call `seeding_summary(self.sid, tf)` (was
      `self.underlying`). Add a comment explaining the engine keys by security_id.

## 2. Test
- [x] 2.1 `test_check_readiness_keys_seeding_by_security_id_not_name`: asserts `seeding_summary` is
      called with `self.sid` (never `self.underlying`) and that an unseeded indicator keyed by that
      sid blocks the component.
- [x] 2.2 Existing readiness tests still pass (6 in `test_directional_strangle.py -k readiness`).
- [x] 2.3 `task test` full green — before archive. **Done (2026-07-17): 1187 passed, 0 failed**
      (full suite, up from the 1146 baseline — includes this change's + the other two in-flight
      changes' tests combined). Ruff on touched files confirmed net-zero new errors vs. HEAD.

## 3. Verify + archive
- [x] 3.1 `openspec validate --strict strangle-readiness-indicators-truthful`.
- [ ] 3.2 Live/boot check: `strategy_not_ready` / readiness chip now reflects real seeding after the
      `indicator-warmup-derive-from-1m` fix seeds EMA depth. **(Next boot.)**
- [ ] 3.3 `openspec archive strangle-readiness-indicators-truthful`.
