"""Settings and engine tests (no live database required)."""

from rag.conf import Settings, get_settings
from rag.infrastructure.db.engine import get_engine
from sqlalchemy.ext.asyncio import AsyncEngine


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"


def test_engine_is_async_and_lazy(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    get_settings.cache_clear()
    assert isinstance(get_engine(), AsyncEngine)
