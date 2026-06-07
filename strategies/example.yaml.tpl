# Strategy configuration template — copy to strategies/<id>.yaml and fill in.
#
# id:    Unique strategy identifier (kebab-case). Must match the file stem.
# class: Dotted Python import path to a class that inherits Strategy ABC.

id: my_strategy
class: pdp.strategies.my_strategy.MyStrategy

watchlist:
  - security_id: "1333"        # Dhan security_id
    exchange_segment: NSE_EQ   # e.g. NSE_EQ, NSE_FNO
    timeframes: [1m, 5m]       # subset of: 1m 5m 15m 30m 1H

params:
  fast_period: 9
  slow_period: 21

risk:
  max_open_orders: 3           # max concurrent OPEN orders for this strategy
  max_daily_loss_inr: 5000     # halt placing new orders if realized loss exceeds this
