## 1. Reproduce and diagnose

- [x] 1.1 `test_late_tick_after_flush_reopens_and_re_closes_the_same_bucket`
      (`tests/market/test_bar_boundary.py`) reproduces the exact aggregator-level duplication
      mechanism; `test_flush_deletes_before_inserting_each_bucket` +
      `test_duplicate_bucket_within_same_batch_is_deduped_before_insert`
      (`tests/market/test_bar_writer.py`) prove the write-path fix closes it
- [x] 1.2 Confirmed: `BarSessionScheduler.flush_session()` resets a builder's `_bar_time` to `None`
      after force-closing it. A late tick (network-delayed, LTT still inside the just-flushed
      bucket) is then treated as a brand-new "first tick" for that same bucket
      (`BarBuilder.push`), and the next boundary-crossing tick emits a **second** `BarClosed` for
      it. This is the actual root cause — not the process-restart hypothesis originally leading in
      the proposal (that remains a secondary possibility the write-path fix also covers, since it's
      timeframe/cause-agnostic).
- [x] 1.3 Scoped audit (2026-07-13, live Mongo, read-only aggregations — a full unscoped
      collection-wide `$group` was too expensive to run safely during market hours and was
      abandoned in favor of `$match`-scoped windows): 2025 sample windows show **zero** duplicates;
      2026-01-01→2026-01-15 shows 72 duplicate buckets; the full 2026-01-01→2026-04-08 window (the
      gap right before the already-fixed 2026-04-08→2026-07-11 range) shows **510** duplicate
      buckets, all on `1D`/`1w` timeframes — `flush_session()` force-closes every configured
      timeframe including daily/weekly, so the same late-tick race applies to them too.

## 2. Fix the write path

- [x] 2.1 `pdp/market/bar_writer.py`: delete-then-insert per exact `(security_id, timeframe, ts)`
      bucket (mirrors `rebuild_market_bars.py`), plus an in-batch dedup pass (last write wins) so
      two enqueues of the same bucket landing in one flush can't both survive `insert_many`
- [x] 2.2 Regression tests from 1.1 pass against the fix
- [x] 2.3 `task test` green (1129 passed)

## 3. Clean up existing duplicates

- [x] 3.1 `scripts/oneoff/dedup_market_bars.py` — finds every duplicate bucket in a date range,
      keeps the highest-`volume` document (the reliable proxy for "most complete aggregation" given
      the late-tick race's second write is typically a low-volume fragment), backs up every
      touched document to JSONL before any delete, `--dry-run` supported and is the only mode
      exercised so far. Offline-tested against a fake collection
      (`tests/scripts/test_dedup_market_bars.py`, 5 tests) and dry-run-verified against live Mongo
      for the 2026-01-01→2026-01-15 window (80 duplicate buckets found, matching the 1.3 audit; zero
      writes made).
- [ ] 3.2 Back up before dedup — **not done for real yet**; the dry-run's JSONL backup output was
      discarded as a validation scratch file, not kept as the real pre-dedup backup
- [ ] 3.3 Run for real — **deliberately not executed.** Deleting documents from a live,
      currently-being-written-to production collection during market hours is exactly the
      hard-to-reverse, shared-system action this session's operating rules require pausing on. The
      script is ready and dry-run-verified; running it for real needs an explicit go-ahead and
      ideally an after-hours window (`docs/RUNBOOK.md`'s existing `mongodump`/JSONL backup
      procedure applies the same way it did for `bar-session-anchoring`'s rebuild).

## 4. Docs + validation

- [x] 4.1 `openspec/specs/market-bars/spec.md`: replaced the stale/never-true "Duplicate bar silently
      skipped" scenario (there is no unique index for Mongo to reject a duplicate write against) with
      "Duplicate bucket write is prevented at the application level", matching the implemented
      delete-then-insert mechanism
- [x] 4.2 `backend/pdp/market/CLAUDE.md`: updated the duplicate-write section with the confirmed root
      cause, the fix, and the audit findings; also fixed a stale `get_mongo_client()` reference in
      `pdp/mongo/CLAUDE.md` and `docs/RUNBOOK.md` (that function doesn't exist — the real API is
      `connect(settings)`/`disconnect(client)`), found while writing the dedup script
- [x] 4.3 `openspec validate --strict market-bars-duplicate-write-fix` — done 2026-07-13, passes

## Blocked / needs explicit go-ahead

Task 3.2/3.3 (real dedup of historical duplicates) is prepared but not executed — see 3.3 above.
Everything else in this change (the write-path fix, which stops *new* duplicates) is complete and
covers the discovered root cause fully.
