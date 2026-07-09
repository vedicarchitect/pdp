from pydantic import BaseModel, ConfigDict
from typing import Any

class GlobalIndicesOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class NewsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class SentimentOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class CommoditiesOut(BaseModel):
    commodities: list[dict[str, Any]]

class VixOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class NextExpiryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class CalendarOut(BaseModel):
    events: list[dict[str, Any]]

class DashboardOut(BaseModel):
    model_config = ConfigDict(extra="allow")
