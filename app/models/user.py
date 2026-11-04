import uuid

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    full_name = Column(String, nullable=True)
    language = Column(String, default="tr")
    currency = Column(String, default="TRY")

    # Bumped on password change/reset to invalidate every issued JWT.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=True, default=utcnow)

    # Subscription. `plan` is "free" or "premium"; premium is only effective
    # while `plan_expires_at` is in the future (see plan_service.effective_plan).
    plan = Column(String, nullable=False, default="free", server_default="free")
    plan_expires_at = Column(DateTime, nullable=True)
    play_purchase_token = Column(String, nullable=True, unique=True, index=True)
    play_product_id = Column(String, nullable=True)

    favorites = relationship("Favorite", back_populates="owner", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    usage = relationship("UsageDaily", cascade="all, delete-orphan")
    device_tokens = relationship("DeviceToken", cascade="all, delete-orphan")

    # SHA-256 of the reset token (never the raw token).
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires = Column(DateTime, nullable=True)

    # SHA-256 of the account-deletion token sent by POST /auth/delete-request.
    delete_token = Column(String, nullable=True, index=True)
    delete_token_expires = Column(DateTime, nullable=True)
