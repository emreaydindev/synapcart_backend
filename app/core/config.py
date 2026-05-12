from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "SynapCart"
    GEMINI_API_KEY: str
    SERP_API_KEY: str
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()