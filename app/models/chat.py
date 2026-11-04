from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base, utcnow


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String)
    created_at = Column(DateTime, default=utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="chat_sessions")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String)  # 'user', 'assistant'
    content = Column(Text)
    # JSON-encoded list of products shown with an assistant answer.
    products = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ChatSession", back_populates="messages")
