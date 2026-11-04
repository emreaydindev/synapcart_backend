from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FavoriteBase(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    price: Optional[float] = None
    currency: Optional[str] = Field(default=None, max_length=8)
    source: Optional[str] = Field(default=None, max_length=200)
    link: str = Field(min_length=1, max_length=2048)
    thumbnail: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, v):
        # The mobile app sends the price as a string; tolerate "1.299,00"-style
        # values and empty strings.
        if v is None or v == "":
            return None
        if isinstance(v, str):
            cleaned = v.replace(" ", "")
            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return v

    @field_validator("link")
    @classmethod
    def _link(cls, v):
        if not v.startswith(("http://", "https://")):
            raise ValueError("Geçersiz ürün linki.")
        return v


class FavoriteCreate(FavoriteBase):
    pass


class FavoriteUpdate(BaseModel):
    # null clears the price alert.
    target_price: Optional[float] = Field(default=None, gt=0, lt=1e9)


class FavoriteResponse(FavoriteBase):
    id: int
    user_id: str
    target_price: Optional[float] = None
    last_checked_price: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    added_at: Optional[datetime] = Field(default=None, validation_alias="created_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
