from pydantic import BaseModel, ConfigDict
from typing import Any

class TrainOut(BaseModel):
    job_id: str
    status: str

class ModelOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class ModelsOut(BaseModel):
    models: list[ModelOut]

class DeployOut(BaseModel):
    status: str
    version: str
