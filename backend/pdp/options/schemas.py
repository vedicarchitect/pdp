from pydantic import BaseModel, ConfigDict
from typing import Any

class ChainOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class MaxPainOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class PcrOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class GexOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class OiHistoryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class OiBuildupOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class OiSeriesOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class StraddleHistoryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class IvHistoryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class FiiDiiOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class FiiDiiHistoryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class RefreshOut(BaseModel):
    status: str
    underlying: str

class PayoffOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class ReadymadesOut(BaseModel):
    model_config = ConfigDict(extra="allow")
