from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestCommissionSettings(BaseModel):
    # Options (Equity) NSE — verified against Dhan charge schedule 2026-06-26
    brokerage_per_order: Decimal = Decimal("20.00")
    stt_rate: Decimal = Decimal("0.0015")          # 0.15% on sell (premium); was wrong at 0.001
    txn_charge_rate: Decimal = Decimal("0.000355299")  # 0.0355299% NSE options on premium
    sebi_rate: Decimal = Decimal("0.000001")        # 0.0001% of turnover; was 10x too high
    stamp_duty_rate: Decimal = Decimal("0.00003")   # 0.003% on buy turnover; was 0.004%
    ipft_rate: Decimal = Decimal("0.000000001")     # 0.0000001% — negligible, included for completeness
    gst_rate: Decimal = Decimal("0.18")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "pdp"
    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    GIT_SHA: str = "local"

    LIVE: bool = False
    BROKER: Literal["paper", "dhan"] = "paper"

    DATABASE_URL: str = Field(...)
    DATABASE_SYNC_URL: str = Field(...)
    REDIS_URL: str = Field(...)

    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""

    # Broker account sync (chunk 2: broker-account-sync)
    BROKER_SYNC_ENABLED: bool = False
    BROKER_SYNC_EOD_TIME: str = "15:45"  # IST HH:MM — daily archival fires after close
    BROKER_ACCOUNT_LABEL: str = "primary"

    DHAN_SCRIPMASTER_URL: str = (
        "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    )
    # Daily filtered scrip-master snapshots: only these underlyings (+ their index rows)
    # are persisted per day for historical (expired-contract) backtest lookups.
    SNAPSHOT_UNDERLYINGS: str = '["NIFTY","BANKNIFTY","SENSEX"]'
    MASTERS_DIR: str = "data/masters"

    PAPER_SLIPPAGE_BPS: float = 2.0

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "pdp"
    MONGO_CHAIN_TTL_DAYS: int = 30

    OPTIONS_POLL_INTERVAL_SECONDS: int = 30
    OPTIONS_RISK_FREE_RATE: float = 0.065
    OPTIONS_UNDERLYINGS: str = '["NIFTY","BANKNIFTY"]'
    OPTIONS_CHAIN_TTL_DAYS: int = 7
    # Options poller is read-only market data; safe to run in paper sessions.
    # Set OPTIONS_POLLER_ENABLED=false to disable without removing credentials.
    OPTIONS_POLLER_ENABLED: bool = True

    PORTFOLIO_MTM_INTERVAL_SECONDS: int = 5
    PORTFOLIO_EOD_SNAPSHOT: bool = True

    RISK_DAILY_LOSS_CAP_INR: float = 50000.0
    RISK_PER_STRATEGY_LOSS_CAP_INR: float = 20000.0
    RISK_SOFT_CAP_PCT: float = 80.0

    # SuperTrend params for the universal IndicatorEngine (rule #4: computed once,
    # strategies consume). Promoted 2026-06-14 from (3,1) to (10,2) after the backtest
    # sweep: ST(10,2) on 15m = PF 4.12 vs ST(3,1) on 5m = PF 0.48 over 83 days.
    SUPERTREND_PERIOD: int = 10
    SUPERTREND_MULTIPLIER: float = 2.0

    # Options warehouse (NIFTY options data pipeline).
    # Cached real expiry-date calendar (built via OI-reset detection from historical data).
    EXPIRY_CACHE_PATH: str = "data/expiry/nifty_expiries.json"
    BANKNIFTY_EXPIRY_CACHE_PATH: str = "data/expiry/banknifty_expiries.json"
    SENSEX_EXPIRY_CACHE_PATH: str = "data/expiry/sensex_expiries.json"
    # Underlyings to warehouse live: any subset of {"NIFTY","BANKNIFTY","SENSEX"}.
    # Set WAREHOUSE_UNDERLYINGS='["NIFTY","BANKNIFTY"]' to enable multi-index mode.
    WAREHOUSE_UNDERLYINGS: list[str] = ["NIFTY"]
    # Standalone warehouser band: current+next weekly (+optional monthly), ATM±N strikes.
    WAREHOUSE_STRIKE_BAND: int = 10
    WAREHOUSE_STRIKE_STEP: int = 50
    WAREHOUSE_INCLUDE_MONTHLY: bool = False
    # Self-healing gap backfill: the running warehouser periodically scans a rolling
    # look-back window for missing option_bars trade-days and auto-backfills them from
    # Dhan (first-write-wins keeps it non-duplicate). Needs Dhan creds at runtime.
    WAREHOUSE_GAP_BACKFILL_ENABLED: bool = True
    WAREHOUSE_GAP_CHECK_INTERVAL_HOURS: float = 4.0
    WAREHOUSE_GAP_LOOKBACK_DAYS: int = 30
    # NSE holiday calendar (JSON {"dates": ["YYYY-MM-DD", ...]}) for trading-day enumeration.
    # Multi-year (2023-2026) so historical gap scans don't treat past holidays as missing days.
    NSE_HOLIDAYS_JSON: str = "data/calendars/nse_holidays_2021_2026.json"
    # Default config YAML loaded by `task backtest` when no --config-file / --config flag is given.
    BACKTEST_DEFAULT_CONFIG: str = "backtest/configs/st10_15m_otm1.yaml"
    # DB-first backtest results (backtest-results-warehouse): results in Mongo, logs in
    # OpenSearch, no local `backtest/runs/<id>/` archive. Short-lived rollback flag only —
    # flip True to restore the old local-file archival if the DB path regresses.
    BACKTEST_ARCHIVE_LOCAL: bool = False

    # ML signal (candlestick-ml-signals capability)
    ML_ENABLED: bool = False                         # master switch; False = no model loaded
    ML_MODEL_DIR: str = "data/models"                # versioned artifact root
    ML_ACTIVE_VERSION: str = ""                      # e.g. "v1"; empty = no model served
    ML_HORIZON: int = 5                              # bars-ahead horizon for directional label
    ML_UP_THRESHOLD: float = 0.002                   # return fraction → "up"
    ML_DOWN_THRESHOLD: float = -0.002                # return fraction → "down"
    ML_EXPIRY_HEAD_ENABLED: bool = False             # phase-2 expiry-close head (off by default)
    ML_EXPIRY_NEAR_THRESHOLD: float = 0.005          # distance fraction → near_above/near_below
    ML_EXPIRY_FAR_THRESHOLD: float = 0.015           # distance fraction → far_above/far_below

    # ── Live event publisher (event-publisher capability) ──────────────────────
    # Continuously monitors manual Dhan positions + the underlying market and emits
    # de-duplicated realtime events to the in-app feed + browser push. Alerts-only.
    EVENTS_ENABLED: bool = True
    # JSON list/dict strings parsed via pdp.events.config helpers (mirrors OPTIONS_UNDERLYINGS).
    EVENTS_SPOT_TIMEFRAMES: str = '["5m","15m","30m","1H","1D"]'
    EVENTS_EMA_PAIRS: str = "[[9,20],[9,50],[20,50]]"     # fast/slow EMA crossover pairs
    EVENTS_PRICE_EMA_PERIODS: str = "[50]"                # EMAs to watch for price crosses
    EVENTS_WATCH_LEVELS: str = "{}"                        # {"NIFTY":[23600,24000]}
    EVENTS_POSITION_RANGES: str = "{}"                    # {"NIFTY:strangle":[23500,24500]}
    EVENTS_PROXIMITY_BAND_PTS: float = 30.0
    EVENTS_CONFLUENCE_MIN: int = 2
    EVENTS_CONFLUENCE_BAND_PTS: float = 25.0
    EVENTS_OTM_DISTANCE_PTS: float = 100.0
    EVENTS_MTM_SWING_INR: float = 5000.0
    EVENTS_TRAIL_GIVEBACK_PCT: float = 30.0
    EVENTS_OI_BUILDUP_PCT: float = 20.0
    EVENTS_OI_VOLUME_SPIKE_Z: float = 3.0
    EVENTS_VOLUME_SPIKE_Z: float = 3.0
    EVENTS_PCR_BANDS: str = "[0.7,1.3]"
    EVENTS_GEX_WALL_PTS: float = 50.0
    EVENTS_DELTA_NEUTRAL_BAND: float = 0.15              # fraction of net qty
    EVENTS_GAP_PCT: float = 0.5
    EVENTS_STATS_INTERVAL_SECONDS: int = 300
    EVENTS_POSITION_SYNC_SECONDS: int = 30
    EVENTS_COOLDOWN_SECONDS: int = 300
    EVENTS_TTL_DAYS: int = 14
    EVENTS_PUSH_ENABLED: bool = False
    EVENTS_PUSH_MIN_SEVERITY: Literal["INFO", "WARNING", "CRITICAL"] = "WARNING"
    EVENTS_VAPID_PUBLIC_KEY: str = ""
    EVENTS_VAPID_PRIVATE_KEY: str = ""
    EVENTS_VAPID_SUBJECT: str = "mailto:ops@pdp.local"

    # Indicator suite defaults (used as fallback; overridden per-entry via watchlist indicators: [...])
    INDICATOR_EMA_PERIODS: str = "9,20,50,100,200"   # comma-separated ints
    INDICATOR_RSI_PERIOD: int = 14
    INDICATOR_PSAR_STEP: float = 0.02
    INDICATOR_PSAR_MAX_STEP: float = 0.2
    INDICATOR_VWMA_PERIOD: int = 20
    INDICATOR_PROFILE_BUCKET_SIZE: float = 50.0       # price-bucket width for VP / MP
    INDICATOR_PROFILE_VALUE_AREA_PCT: float = 0.70    # VP value-area coverage

    backtest_commission: BacktestCommissionSettings = BacktestCommissionSettings()

    # ── Unified OpenSearch log pipeline (trade-analysis-feedback-loop capability) ──
    # Every backend + Flutter UI log auto-ships to OpenSearch in realtime through one
    # non-blocking indexer, segregated by `source`. Disabled by default; the URL is the
    # only thing that changes between local compose and AWS OpenSearch Service (chunk 16).
    OPENSEARCH_ENABLED: bool = False
    OPENSEARCH_URL: str = "http://localhost:9200"
    OPENSEARCH_USER: str = ""
    OPENSEARCH_PASSWORD: str = ""
    OPENSEARCH_VERIFY_CERTS: bool = False
    OPENSEARCH_INDEX_PREFIX: str = "pdp"
    OPENSEARCH_BULK_INTERVAL: float = 2.0   # seconds between background bulk flushes
    OPENSEARCH_BULK_MAX: int = 500          # flush early once this many docs are queued
    OPENSEARCH_QUEUE_MAX: int = 10000       # drop-on-full beyond this (never blocks callers)
    OPENSEARCH_LOG_LEVEL: str = "INFO"      # min structlog level shipped to pdp-logs-*

    # ── Ops safety net (ops-safety-net capability) ────────────────────────
    ERRORS_JSONL_PATH: str = "logs/errors.jsonl"  # ERROR-only structured log sink
    ERRORS_JSONL_MAX_LINES: int = 1000            # truncate on startup if file exceeds this
    LOG_REDACTION_ENABLED: bool = True            # redact secrets from all log sinks
    FEED_STALE_HALT_SECONDS: int = 180            # sustained stale seconds → kill-switch engage

    # ── Market feed resilience (market-feed-resilience capability) ────────
    FEED_STALE_SECONDS: int = 60            # seconds without a tick before feed_stale fires
    FEED_RECONNECT_BASE_DELAY: float = 1.0  # initial reconnect back-off (seconds)
    FEED_RECONNECT_MAX_DELAY: float = 30.0  # cap for exponential reconnect back-off
    SCRIP_REFRESH_ENABLED: bool = False     # daily pre-open scrip master refresh
    SCRIP_REFRESH_TIME: str = "08:45"       # IST HH:MM for the daily refresh

    # ── Order pre-flight safety net (broker-order-safety capability) ───────
    ORDER_PREFLIGHT_ENABLED: bool = True
    MARGIN_CHECK_ENABLED: bool = False      # live Dhan margin API; off until creds confirmed
    MARGIN_BUFFER_PCT: float = 5.0          # block if required > available × (1 - buffer/100)
    MARGIN_FAILOPEN: bool = False           # fail-closed in live by default; True = advisory
    FREEZE_QTY_BY_UNDERLYING: dict[str, int] = {
        "NIFTY": 1800,
        "BANKNIFTY": 900,
        "SENSEX": 1000,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
