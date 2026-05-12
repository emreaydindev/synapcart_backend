from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: str
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str