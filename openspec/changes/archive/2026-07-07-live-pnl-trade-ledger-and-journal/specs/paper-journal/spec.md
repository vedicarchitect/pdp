## MODIFIED Requirements

### Requirement: Daily P&L and progress stats

The system SHALL compute, for a given day, the total premium sold and bought, net premium,
total charges, realized P&L, round-trip count, wins, losses, and win-rate. Realized P&L SHALL
be the sum of P&L over **completed round-trips only** (matched buy↔sell pairs, net of charges);
an open position (sold but not yet bought back, or vice-versa) SHALL contribute zero to
realized P&L. The all-fills `sell_value − buy_value − charges` figure SHALL NOT be reported as
realized P&L; gross premium sold/bought and total charges remain informational lines. For
strangle strategies the journal's trade source SHALL be the enriched entry→exit ledger
(`live-trade-ledger`), so the journal's realized P&L for a given day+strategy equals the
`/strangle/trades` realized total for the same day+strategy.

#### Scenario: Realized P&L net of charges

- **WHEN** a day's fills are fully round-tripped (flat by EOD)
- **THEN** realized P&L equals total sell proceeds minus total buy cost minus total charges

#### Scenario: An open position contributes zero to realized P&L

- **WHEN** a day has one short sold at 100 that has not been bought back by EOD
- **THEN** realized P&L for that day is 0 for that position — its full sell premium is NOT
  booked as realized

#### Scenario: Journal realized reconciles with the trade ledger

- **WHEN** the journal realized P&L and the `/strangle/trades` realized total are computed for
  the same strangle strategy on the same day
- **THEN** the two figures are equal, because both derive from the same matched round-trips
