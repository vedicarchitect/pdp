## ADDED Requirements

### Requirement: Daily Camarilla levels SHALL be derived from daily bars

The bias engine's `cam_daily` input SHALL read the pivot tracker on the `1D` timeframe. It SHALL NOT
read an intraday timeframe, because a Camarilla pivot describes the prior period's high-low-close and
an intraday pivot therefore describes the prior intraday bar, not the prior trading day.

#### Scenario: Daily Camarilla reflects the prior session

- **WHEN** the strategy builds bias inputs at 10:20 IST
- **THEN** `cam_daily` is computed from the previous trading day's high, low and close

#### Scenario: Intraday pivots are not used as daily levels

- **WHEN** `_build_bias_inputs` requests Camarilla levels
- **THEN** no request is made for pivots on the `5m` timeframe

### Requirement: Weekly Camarilla levels SHALL have a configured tracker

Every strategy that assigns a non-zero `w_cam_weekly` SHALL declare the `1w` timeframe with the
`pivots` family in its watchlist, so the tracker the bias engine reads exists.

#### Scenario: Weekly pivot resolves

- **WHEN** the strategy builds bias inputs after warmup on a configured `1w` watchlist entry
- **THEN** `cam_weekly` is non-null and reflects the prior ISO week's high, low and close

#### Scenario: Weekly pivot is seeded from history

- **WHEN** warmup runs for the `1w` timeframe
- **THEN** the pivot tracker is seeded from stored weekly bars, not from the current partial week alone

### Requirement: Every options underlying the strategy trades SHALL have a polled option chain

An underlying traded by a live strategy that assigns a non-zero `w_pcr` SHALL appear in
`OPTIONS_UNDERLYINGS` so a chain poller runs and `get_pcr(underlying)` can return a value. Because
`OPTIONS_UNDERLYINGS` is set in the environment file, the environment value SHALL be treated as
authoritative over the code default, and deployment verification SHALL query the running service
rather than inspect source.

#### Scenario: SENSEX PCR is available

- **WHEN** the SENSEX strangle evaluates bias during market hours
- **THEN** `chain_hub.get_pcr("SENSEX")` returns a value and the `pcr` vote is not an abstention

#### Scenario: Environment overrides code default

- **WHEN** `OPTIONS_UNDERLYINGS` is present in the environment file
- **THEN** its value governs and a change to the `settings.py` default alone has no effect

### Requirement: Startup SHALL fail when a strategy weights a bias input its configuration cannot supply

At strategy load, for every bias weight greater than zero, the platform SHALL verify the
corresponding input is satisfiable from that strategy's watchlist and the active settings, and SHALL
raise naming the weight and the missing requirement when it is not. A weight of zero SHALL impose no
requirement.

#### Scenario: Weighted input has no timeframe

- **WHEN** a strategy sets `w_cam_weekly: 1.0` and its watchlist omits the `1w` timeframe
- **THEN** startup fails with a message naming `w_cam_weekly` and the missing `1w` + `pivots` requirement

#### Scenario: Weighted input has no indicator family

- **WHEN** a strategy sets `w_ema_1h: 2.5` and its `1H` watchlist entry omits the `ema` family
- **THEN** startup fails naming `w_ema_1h` and the missing family

#### Scenario: Weighted PCR without a chain

- **WHEN** a strategy sets `w_pcr: 1.0` for an underlying absent from `OPTIONS_UNDERLYINGS`
- **THEN** startup fails naming `w_pcr` and the missing underlying

#### Scenario: Zeroed weight imposes no requirement

- **WHEN** a strategy sets `w_cam_weekly: 0.0` and omits the `1w` timeframe
- **THEN** startup succeeds

#### Scenario: Fully satisfiable configuration

- **WHEN** every non-zero weight has its timeframe, family and settings prerequisites present
- **THEN** startup succeeds and the check logs the satisfied input set

### Requirement: Bias evaluation SHALL log its per-input vote breakdown

Each bias evaluation SHALL emit the per-input vote, weight and abstention status, so that a
permanently-abstaining input is visible in the session log rather than inferred from the distribution
of resulting buckets.

#### Scenario: Abstention is visible

- **WHEN** an input returns no vote because its value is null
- **THEN** the emitted breakdown records that input as abstaining, with its configured weight

#### Scenario: Breakdown accompanies the bucket

- **WHEN** the bias engine resolves a bucket
- **THEN** the emitted record carries the bucket, the final score, and the vote and weight of every input
