## MODIFIED Requirements

### Requirement: Bucket changes require sustained confirmation
The strategy SHALL require a new bias bucket to persist for `bucket_confirm_bars` consecutive bars
before it closes and reopens legs for that bucket.

`bucket_confirm_bars` defaults to 2. A bucket that reverts before confirmation MUST reset the
confirmation counter and leave the open legs untouched.

The strategy SHALL commit the bucket transition — advancing `current_bucket` to the confirmed
bucket and clearing the pending-confirmation counter — **only after an open attempt actually opens
at least one leg**. When a confirmed bucket's open attempt opens no legs (e.g. a transient
fill-price failure), the strategy MUST NOT advance `current_bucket`; it MUST retain the pending
bucket so the next decision bar retries the open, rather than latching the bucket and never
retrying for the rest of the day. A bar on which entry is not allowed (e.g. outside the DTE entry
window) MUST NOT advance `current_bucket` either.

#### Scenario: Single-bar flip does not churn legs
- **WHEN** the bucket changes for one bar and reverts on the next, with `bucket_confirm_bars = 2`
- **THEN** the strategy does not close or reopen any legs

#### Scenario: Sustained change acts after confirmation
- **WHEN** a new bucket persists for `bucket_confirm_bars` consecutive bars
- **THEN** the strategy closes the current legs and reopens for the new bucket

#### Scenario: Failed open retries on the next bar instead of latching
- **WHEN** a confirmed bucket's open attempt opens no legs because the option's fill price could
  not be resolved
- **THEN** `current_bucket` is not advanced and the next decision bar attempts the open again

## ADDED Requirements

### Requirement: Entry open resolves a fill price before aborting
When opening a short or hedge leg, the strategy SHALL subscribe the option's market feed and then
wait, up to a bounded configurable timeout (`entry_ltp_wait_s`), for the option's first live LTP
before deciding the leg cannot be priced. A leg SHALL be aborted only when no fill price can be
resolved after that wait and all existing fallback layers are exhausted; a freshly-subscribed
option that has simply not yet produced its first tick MUST NOT cause an immediate abort.

An aborted open MUST leave no untracked broker position — any placed-but-unfilled entry order for
the leg SHALL be cancelled.

#### Scenario: First tick arrives within the wait window
- **WHEN** an option is subscribed at open time and produces its first tick within `entry_ltp_wait_s`
- **THEN** the leg is priced from that tick and opened, rather than aborted

#### Scenario: No tick within the wait window aborts cleanly
- **WHEN** no LTP can be resolved for the option within `entry_ltp_wait_s` and every fallback layer
  is cold
- **THEN** the leg is aborted, any placed entry order is cancelled, and no untracked position remains

### Requirement: Aborted entries are surfaced as events
The strategy SHALL emit a canonical `entry_aborted` event whenever an entry open attempt is aborted
or opens fewer legs than the confirmed bucket requires, carrying the bias bucket, the requested
PE/CE lot counts, and a machine-readable reason, into the same activity log and monitor payload as
other strangle events. A silent no-trade (an evaluated bucket that opens no legs) MUST be
observable from the strategy's event stream, not only from process stdout.

#### Scenario: Abort is visible in the activity log
- **WHEN** a confirmed bucket's open attempt opens no legs
- **THEN** an `entry_aborted` event is recorded with the bucket, requested lots, and reason
