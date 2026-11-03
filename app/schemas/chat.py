import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=settings.MAX_MESSAGE_LENGTH)

    @field_validator("message")
    @classmethod
    def _strip(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Mesaj boş olamaz.")
        return v


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class SessionResponse(BaseModel):
    id: int
    user_id: str
    title: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Product(BaseModel):
    title: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None
    link: Optional[str] = None
    thumbnail: Optional[str] = None


class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    products: Optional[List[Product]] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("content", mode="before")
    @classmethod
    def _content(cls, v):
        return v or ""

    @field_validator("products", mode="before")
    @classmethod
    def _products(cls, v: Any):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return None
        return v


class AgentResponse(BaseModel):
    status: str
    analysis: str
    products: List[Product] = []
