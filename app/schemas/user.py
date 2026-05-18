from typing import Optional

from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: EmailStr

class UserLogin(UserBase):
    password: str

class UserCreate(UserBase):
    password: str
    name: str

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
    user_name: Optional[str] = None

class PasswordResetRequest(BaseModel):
    email: str

class PasswordReset(BaseModel):
    token: str
    new_password: str