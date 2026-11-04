from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated


class Settings(BaseSettings):
    PROJECT_NAME: str = "SynapCart"
    ENV: str = "dev"  # "dev" | "prod"
    # Run Alembic migrations on startup. Disable when the deploy runs them
    # as a separate step (render.yaml does).
    AUTO_MIGRATE: bool = True

    GEMINI_API_KEY: str
    SERP_API_KEY: str
    DATABASE_URL: str
    SECRET_KEY: str

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week

    # Comma-separated list of allowed browser origins.
    CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "https://synapcart-web.vercel.app",
        "http://localhost:3000",
    ]

    APP_FRONTEND_URL: str = "https://synapcart.app"

    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str  # Gmail address
    SMTP_PASSWORD: str  # App password
    RESET_TOKEN_EXPIRE_HOURS: int = 1
    DELETE_TOKEN_EXPIRE_HOURS: int = 24

    # Agent limits
    MAX_MESSAGE_LENGTH: int = 1000
    AGENT_RATE_LIMIT: str = "20/minute"
    GEMINI_TIMEOUT_SECONDS: float = 30.0

    # Premium analyst model (free users get gemini_service.DEFAULT_MODEL).
    PREMIUM_ANALYST_MODEL: str = "gemini-2.5-flash"

    # Google Play Billing. The service account needs "View financial data" in
    # Play Console. GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is the key file's JSON
    # content (or a path to it). Unset = /billing/google/verify returns 503.
    PLAY_PACKAGE_NAME: str = "com.neilb.synapcart"
    PLAY_SUBSCRIPTION_IDS: Annotated[List[str], NoDecode] = ["synapcart_premium"]
    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON: str = ""
    # Shared secret for the Pub/Sub push endpoint (?token=...). Unset = RTDN disabled.
    PLAY_RTDN_TOKEN: str = ""

    # Firebase Cloud Messaging (price alerts). Service account JSON content or
    # path; FIREBASE_PROJECT_ID defaults to the key's project_id.
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""
    FIREBASE_PROJECT_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("CORS_ORIGINS", "PLAY_SUBSCRIPTION_IDS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() in ("prod", "production")

    @model_validator(mode="after")
    def _check_secret(self):
        if self.is_prod and len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return self


settings = Settings()
