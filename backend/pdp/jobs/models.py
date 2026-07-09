from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pdp.db.base import Base


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default=JobStatus.PENDING.value)
    params = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    progress = Column(Integer, default=0)
    progress_message = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)
    logs = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "type": self.type,
            "status": self.status,
            "params": self.params,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "logs": self.logs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }
