## ADDED Requirements

### Requirement: Hedge legs record the day P&L baseline
The strategy SHALL record the per-security day P&L baseline when opening a hedge leg, the same way
it does for short and momentum legs.

Without this, the hedge security's realized P&L is not baselined and `_day_realized()` mis-counts the
day total.

#### Scenario: Hedge open baselines the security
- **WHEN** a hedge leg is opened for a security
- **THEN** the strategy records that security's current realized P&L as the day baseline before
  placing the order, identically to short and momentum opens

### Requirement: Bias score uses the full configured signal set
The strategy SHALL provide live inputs for every configured bias signal so that each contributes a
vote when its data is available, rather than leaving votes permanently absent.

This covers: `ema_1h` and `ema_15m` (seeded by warmup before the first bar), `cam_weekly` (from a
weekly `1w` pivot snapshot), `vwap` (computed from index **futures** volume, since an index spot has
no traded volume), and `pcr` (derived from the option-chain poller). The intent is to dilute any
single signal's influence so a lone `ema_5m` flip no longer changes the bucket on its own.

#### Scenario: All configured signals vote when warmed
- **WHEN** the engine evaluates bias after warmup and chain data are available
- **THEN** the `bias_evaluated.votes` record contains entries for `ema_1h`, `ema_15m`, `ema_5m`,
  `cam_daily`, `cam_weekly`, `swing`, `vwap`, `orb`, and `pcr`

#### Scenario: VWAP comes from futures, not the index spot
- **WHEN** the VWAP signal is computed for an index-driven strangle
- **THEN** it is derived from the index futures' volume-bearing bars
- **AND** it produces a non-null vote once futures volume is non-zero

#### Scenario: A missing data source skips only its own vote
- **WHEN** one signal's data is unavailable (e.g. chain not yet polled for `pcr`)
- **THEN** only that signal's vote is omitted and the remaining signals still vote

### Requirement: Bucket changes require sustained confirmation
The strategy SHALL require a new bias bucket to persist for `bucket_confirm_bars` consecutive bars
before it closes and reopens legs for that bucket.

`bucket_confirm_bars` defaults to 2. A bucket that reverts before confirmation MUST reset the
confirmation counter and leave the open legs untouched.

#### Scenario: Single-bar flip does not churn legs
- **WHEN** the bucket changes for one bar and reverts on the next, with `bucket_confirm_bars = 2`
- **THEN** the strategy does not close or reopen any legs

#### Scenario: Sustained change acts after confirmation
- **WHEN** a new bucket persists for `bucket_confirm_bars` consecutive bars
- **THEN** the strategy closes the current legs and reopens for the new bucket

### Requirement: Day-loss halt survives a restart
The strategy SHALL persist a per-strategy, per-IST-day halt marker when `day_loss_cap` triggers, and
on startup SHALL remain halted for the rest of that trading day if the marker is set.

The marker MUST be keyed by strategy id and IST trading day, and MUST clear on IST date rollover so
the next day starts un-halted.

#### Scenario: Restart on the same day stays halted
- **WHEN** `day_loss_cap` has fired for a strategy today, the strategy is restarted, and the first
  bar of the same IST day is processed
- **THEN** the strategy is halted and does not open new legs

#### Scenario: Next day resumes
- **WHEN** the IST trading day rolls over after a halt
- **THEN** the halt marker is cleared and the strategy may open legs again
