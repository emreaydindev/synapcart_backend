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

    favorites = relationship("Favorite", back_populates="owner", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")

    # SHA-256 of the reset token (never the raw token).
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires = Column(DateTime, nullable=True)
