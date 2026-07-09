from pydantic import BaseModel, ConfigDict
from typing import Any

class LogsResponseOut(BaseModel):
    count: int
    logs: list[dict[str, Any]]

class SessionResponseOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class IngestResponseOut(BaseModel):
    accepted: int
