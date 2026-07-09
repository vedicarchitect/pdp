from pydantic import BaseModel, ConfigDict

class ScreenerOut(BaseModel):
    model_config = ConfigDict(extra="allow")
