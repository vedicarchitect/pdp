from pydantic import BaseModel, ConfigDict
from typing import Any

class JobOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class JobListOut(BaseModel):
    jobs: list[dict[str, Any]]

class JobActionOut(BaseModel):
    status: str
