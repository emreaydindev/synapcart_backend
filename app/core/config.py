from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "SynapCart"
    GEMINI_API_KEY: str
    SERP_API_KEY: str
    DATABASE_URL: str
    SECRET_KEY: str

    APP_FRONTEND_URL: str = "https://synapcart.app"

    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str  # Gmail address
    SMTP_PASSWORD: str  # App password
    RESET_TOKEN_EXPIRE_HOURS: int = 1
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()