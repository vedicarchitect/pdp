from pydantic import BaseModel, ConfigDict
from typing import Any

class CoverageOut(BaseModel):
    model_config = ConfigDict(extra="allow")
