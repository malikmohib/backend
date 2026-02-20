from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env2",
        env_file_encoding="utf-8",
        extra="ignore",   # ✅ ignore unknown keys in .env2
    )

    DATABASE_URL: str

    JWT_SECRET: str
    JWT_ACCESS_MINUTES: int = 30
    JWT_REFRESH_DAYS: int = 14
    JWT_ALG: str = "HS256"

    BOT_API_KEY: str = "change-me"


settings = Settings()
