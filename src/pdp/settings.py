from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    DHAN_SCRIPMASTER_URL: str = (
        "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    )

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
