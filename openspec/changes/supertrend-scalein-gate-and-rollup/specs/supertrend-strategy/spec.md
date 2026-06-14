## MODIFIED Requirements

### Requirement: Scale-in while trend holds
The strategy SHALL add a configured number of lots on each subsequent signal bar while the
SuperTrend direction is unchanged, up to a configured maximum lot count. The strategy SHALL add lots
only when the open leg's option premium did NOT make a new high on the current bar relative to the
immediately preceding bar (current bar high <= prior bar high). When the current bar's premium high
exceeds the prior bar's high, the strategy SHALL defer the add and re-evaluate the same gate on each
subsequent bar, adding as soon as a bar fails to exceed the prior bar's high (still subject to the
maximum lot count). When no prior bar is available, the gate SHALL allow the add. A deferred add
SHALL NOT change the position's held quantity.

#### Scenario: Add a lot on continued trend
- **WHEN** a leg is open, the direction is unchanged on a new bar, open lots < max, and the leg's
  premium high on this bar does not exceed the prior bar's high
- **THEN** the strategy sells `add_lots` more of the same option

#### Scenario: Respect the max-lots cap
- **WHEN** open lots already equal the maximum
- **THEN** the strategy does not add more lots

#### Scenario: Premium breakout defers the add
- **WHEN** a leg is open, the direction is unchanged, open lots < max, but the leg's premium high on
  the current bar exceeds the prior bar's high
- **THEN** the strategy adds no lot on that bar, the held quantity is unchanged, and the gate is
  re-evaluated on the next bar

#### Scenario: Add resumes once the premium stops making new highs
- **WHEN** a previously deferred add is pending and a later bar's premium high does not exceed its
  prior bar's high
- **THEN** the strategy sells `add_lots` more of the same option on that bar (subject to the max)

## ADDED Requirements

### Requirement: Premium-decay roll-up
The strategy SHALL, when the open leg's option premium falls below a configured roll trigger
(`roll_trigger_prem`, defaulting to 20) and the SuperTrend direction is unchanged, buy back the
entire open leg and re-sell a richer same-side strike, opening at the starting lot count. The roll
target SHALL be the furthest-out-of-the-money same-side strike within the warehouse band whose
current premium exceeds a configured floor (`roll_target_min_prem`, defaulting to 50). If no same-side
strike within the band clears the floor, the strategy SHALL NOT roll and SHALL hold the existing leg.
A direction flip against the open leg SHALL take precedence over a roll, and the strategy SHALL NOT
add scale-in lots on the same bar as a roll.

#### Scenario: Premium decays below trigger rolls into a richer strike
- **WHEN** a short leg is open, the direction is unchanged, and the leg's premium is below
  `roll_trigger_prem`
- **THEN** the strategy buys back the full leg and sells the furthest-OTM same-side strike whose
  premium exceeds `roll_target_min_prem`, at the starting lot count

#### Scenario: No qualifying strike holds the leg
- **WHEN** a roll is triggered but no same-side strike within the band has a premium above
  `roll_target_min_prem`
- **THEN** the strategy does not roll and keeps the existing leg

#### Scenario: Flip takes precedence over a roll
- **WHEN** the leg's premium is below `roll_trigger_prem` but the SuperTrend direction has flipped
  against the leg on the same bar
- **THEN** the strategy reverses the leg (flip) rather than rolling

#### Scenario: Roll opens only starting lots that bar
- **WHEN** a roll-up occurs
- **THEN** the new leg opens at the starting lot count and no scale-in lot is added on the roll bar

### Requirement: Closes settle the exact held quantity
The strategy SHALL, on every close of an open leg - flip-driven reverse, per-leg stop, daily-cap
flatten, premium-decay roll-up, and end-of-session square-off - buy back exactly the quantity
currently held in the open position (its accumulated lots after any gated scale-ins and prior rolls)
and value the close at the leg's actual average entry. The strategy SHALL read live position state
for each close and SHALL NOT assume a fixed, starting, or maximum lot count.

#### Scenario: Square-off closes only the held lots
- **WHEN** the premium-breakout gate deferred adds so the open leg holds fewer than the maximum lots
  and the square-off time is reached
- **THEN** the strategy buys back exactly the lots currently held, not the maximum

#### Scenario: Close after a roll settles the rolled leg's quantity
- **WHEN** a roll-up has reset the leg to the starting lot count and a flip or square-off then closes it
- **THEN** the buy-back quantity equals the rolled leg's current lots, not the pre-roll quantity

#### Scenario: Deferred add creates no phantom quantity
- **WHEN** a scale-in add was deferred by the premium-breakout gate
- **THEN** the position's held quantity does not include the deferred lot in any later close
