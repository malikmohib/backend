from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
ENV_PATH = BASE_DIR / ".env2"

# ✅ Force load .env into environment variables first
load_dotenv(dotenv_path=ENV_PATH)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ISSUER: str = "certify-dashboard"
    JWT_EXPIRE_MINUTES: int = 720
    BOT_API_KEY: str = "change-me"

settings = Settings()

# ✅ Optional debug (remove later)
# print("Loaded DATABASE_URL =", os.getenv("DATABASE_URL"))
