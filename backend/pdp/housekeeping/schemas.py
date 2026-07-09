from pydantic import BaseModel

class HousekeepingOut(BaseModel):
    job_id: str
    status: str
