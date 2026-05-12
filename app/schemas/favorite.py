from pydantic import BaseModel, HttpUrl
from typing import Optional

class FavoriteBase(BaseModel):
    title: str
    price: float
    source: str
    link: str
    thumbnail: Optional[str] = None

class FavoriteCreate(FavoriteBase):
    pass

class FavoriteResponse(FavoriteBase):
    id: int
    user_id: str

    class Config:
        from_attributes = True