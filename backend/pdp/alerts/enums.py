from enum import Enum


class AlertCondition(str, Enum):
    PRICE_GT = "PRICE_GT"
    PRICE_LT = "PRICE_LT"
    DELTA_GT = "DELTA_GT"
    DELTA_LT = "DELTA_LT"
    GAMMA_GT = "GAMMA_GT"
    GAMMA_LT = "GAMMA_LT"
    VEGA_GT = "VEGA_GT"
    VEGA_LT = "VEGA_LT"
    PNL_GT = "PNL_GT"
    PNL_LT = "PNL_LT"


class AlertChannel(str, Enum):
    WS = "WS"
    TELEGRAM = "TELEGRAM"


class AlertStatus(str, Enum):
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    RESOLVED = "RESOLVED"
