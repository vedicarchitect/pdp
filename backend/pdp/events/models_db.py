"""PostgreSQL model for Web Push subscriptions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pdp.db.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    endpoint: Mapped[str] = mapped_column(String, primary_key=True)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
