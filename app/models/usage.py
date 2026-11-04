from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String

from app.core.database import Base, utcnow


class UsageDaily(Base):
    """Agent messages per user per UTC day (the free plan's daily quota)."""

    __tablename__ = "usage_daily"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    date = Column(Date, primary_key=True)
    messages = Column(Integer, nullable=False, default=0, server_default="0")


class DeviceToken(Base):
    """FCM registration tokens for push notifications (price alerts)."""

    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    platform = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True, default=utcnow)
    updated_at = Column(DateTime, nullable=True, default=utcnow, onupdate=utcnow)
