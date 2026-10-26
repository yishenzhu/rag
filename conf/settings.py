"""Infrastructure settings loaded from environment variables and .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"
    api_key_pepper: str = "dev-pepper-change-me"
    jwt_secret: str = "dev-jwt-secret-change-me-0123456789abcdef"
    jwt_access_ttl_seconds: int = 900
    rate_limit_rate: int = 20
    rate_limit_burst: int = 40


@lru_cache
def get_settings() -> Settings:
    return Settings()
