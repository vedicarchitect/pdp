Create a complete, ready-to-code intraday directional option-selling strategy with the following exact rules.

### Time & Session
- Indian market (NSE)
- Premarket: 09:00 – 09:07
- Market open: 09:15
- Opening Range Breakout (ORB) candle: 09:15 – 09:30 (15-min candle)
- Trading allowed only after ORB is fully formed
- DTE must be strictly less than 7 (prefer 0–3 DTE for higher premium decay)
- Timeframes: 5-min (primary) + 15-min (confirmation / scaling)

### Indicators (apply on underlying index/spot – Nifty / BankNifty)
- EMA 9 & EMA 20
- SuperTrend (period=10, multiplier=2)
- VWAP (session) future or option price?
- ORB High / ORB Low (from 09:15–09:30 candle)
- Camarilla pivots: S3, S4, R3, R4 (calculated from previous day H/L/C)

Also plot SuperTrend (10,2) on the option chart itself (5-min).

### Position Sizing
- Initial quantity = 3 lots (configurable)
- Scale-in every 15 minutes while the trend remains valid
- Quantity sequence: 3 → 6 → 9 lots (max 9 lots, configurable)
- Max loss for the day = ₹10,000 (configurable hard stop)

### Strike Selection
- Prefer ATM or 1–2 strikes ITM (make this configurable for backtesting)
- Optional hedge: buy far OTM option of same expiry with premium ₹2–5 (configurable on/off)

### Bullish Directional Sell (Sell PE)
Entry conditions (all must be true on 5-min):
1. Price > ORB Low
2. Price > VWAP
3. SuperTrend is green (bullish)
4. EMA 9 crosses above EMA 20 (or already above and sloping up)

Enter short PE with initial 3 lots.
Scale up every 15 minutes as long as all above conditions remain true, up to max 9 lots.(maxx lot configurable)

### Bearish Directional Sell (Sell CE)
Entry conditions (all must be true on 5-min):
1. Price < ORB High
2. Price < VWAP
3. SuperTrend is red (bearish)
4. EMA 9 crosses below EMA 20 (or already below and sloping down)

Enter short CE with initial 3 lots.
Scale up every 15 minutes as long as all above conditions remain true, up to max 9 lots.

### Exit Rules (any one triggers exit of the entire position)
1. 20-EMA is broken and the break sustains for 15 minutes (i.e., three consecutive 5-min candles close on the wrong side of 20-EMA)
2. SuperTrend on the underlying flips colour
3. SuperTrend on the option chart (5-min) flips colour
4. Price is rejected from any Camarilla level (S3/S4/R3/R4) and the rejection sustains for 30 minutes
5. Premium of the sold option rises by 1% from entry average
6. Unrealised loss reaches 20% of current position value
7. Daily max loss of ₹10,000 is hit
8. Time-based exit: square-off all positions by 15:15 (or configurable)

### Additional Requirements
- Only one directional position at a time (either PE sell or CE sell)
- No overnight positions
- Log every entry, scale-in, and exit reason with timestamp, price, premium, and P&L
- Make all key parameters configurable: initial lots, max lots, scale-in interval, ITM depth, hedge on/off, max loss, exit %, DTE filter, etc.
- Prefer clean, modular code structure so the strategy can be backtested easily on historical data and then live-traded.

Generate the full strategy logic, entry/exit pseudo-code, parameter list, and any necessary risk-management notes.