from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_BYTES

SUPPORTED_LANGUAGES = {"tr", "en", "ar", "ru", "fr", "de", "es", "it", "zh", "ja"}
SUPPORTED_CURRENCIES = {"TRY", "USD", "EUR", "GBP"}
MIN_PASSWORD_LENGTH = 8


def _normalize_email(v: str) -> str:
    return v.strip().lower() if isinstance(v, str) else v


def validate_new_password(v: str) -> str:
    if len(v) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalıdır.")
    if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("Şifre çok uzun.")
    if v.isdigit() or v.isalpha():
        raise ValueError("Şifre hem harf hem rakam içermelidir.")
    return v


class UserBase(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def _email_lower(cls, v):
        return _normalize_email(v)


class UserLogin(UserBase):
    password: str = Field(max_length=256)


class UserCreate(UserBase):
    password: str
    name: str = Field(min_length=1, max_length=80)

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_new_password(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("İsim boş olamaz.")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=80)
    language: Optional[str] = None
    currency: Optional[str] = None

    @field_validator("language")
    @classmethod
    def _language(cls, v):
        if v is None:
            return v
        v = v.lower()
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError("Desteklenmeyen dil.")
        return v

    @field_validator("currency")
    @classmethod
    def _currency(cls, v):
        if v is None:
            return v
        v = v.upper()
        if v not in SUPPORTED_CURRENCIES:
            raise ValueError("Desteklenmeyen para birimi.")
        return v


class UserResponse(UserBase):
    id: str
    full_name: Optional[str]
    language: str
    currency: str
    created_at: Optional[datetime] = None
    # Effective plan ("free" | "premium"); premium may carry an expiry.
    plan: str = "free"
    plan_expires_at: Optional[datetime] = None
    usage_today: Optional[int] = None
    daily_limit: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class DeviceTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    platform: Optional[str] = Field(default="android", max_length=20)


class Token(BaseModel):
    access_token: str
    token_type: str
    user_name: Optional[str] = None


class PasswordResetRequest(UserBase):
    pass


class AccountDeleteRequest(UserBase):
    pass


class AccountDeleteConfirm(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class PasswordReset(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v):
        return validate_new_password(v)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v):
        return validate_new_password(v)


class AccountDelete(BaseModel):
    password: Optional[str] = Field(default=None, max_length=256)
