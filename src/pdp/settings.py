from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestCommissionSettings(BaseModel):
    brokerage_per_order: Decimal = Decimal("20.00")
    stt_rate: Decimal = Decimal("0.001")
    txn_charge_rate: Decimal = Decimal("0.0003553")
    sebi_rate: Decimal = Decimal("0.00001")
    stamp_duty_rate: Decimal = Decimal("0.00004")
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

    # Options warehouse + historical migration (NIFTY options data pipeline).
    # External, read-only "abi project" DuckDB source (PDP and Abi are siblings).
    ABI_NIFTY_DUCKDB: str = "../Abi/data/historicaldata/nifty.db"
    # Cached real expiry-date calendar (built via OI-reset detection from the source).
    EXPIRY_CACHE_PATH: str = "data/expiry/nifty_expiries.json"
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
    NSE_HOLIDAYS_JSON: str = "data/calendars/nse_holidays_2023_2026.json"
    # Abi DuckDB data cutoff: gap-fill starts from this date by default.
    ABI_CUTOFF_DATE: str = "2026-05-23"

    backtest_commission: BacktestCommissionSettings = BacktestCommissionSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
