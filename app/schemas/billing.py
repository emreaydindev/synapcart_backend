from typing import Optional

from pydantic import BaseModel, Field


class PlayVerifyRequest(BaseModel):
    purchase_token: str = Field(min_length=1, max_length=4096)
    product_id: str = Field(min_length=1, max_length=200)


class PubSubMessage(BaseModel):
    data: Optional[str] = None
    messageId: Optional[str] = None


class PubSubPush(BaseModel):
    message: PubSubMessage
    subscription: Optional[str] = None
