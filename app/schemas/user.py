from typing import Optional

from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    language: Optional[str] = None
    currency: Optional[str] = None

class UserResponse(UserBase):
    id: str
    full_name: Optional[str]
    language: str
    currency: str
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str