from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


def _reload_settings_module():
    import pdp.settings as s

    importlib.reload(s)
    return s


def test_live_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE", raising=False)
    s = _reload_settings_module()
    settings = s.Settings()  # type: ignore[call-arg]
    assert settings.LIVE is False
    assert settings.BROKER == "paper"


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_SYNC_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    s = _reload_settings_module()
    with pytest.raises(ValidationError):
        s.Settings()  # type: ignore[call-arg]


def test_mongo_defaults() -> None:
    s = _reload_settings_module()
    settings = s.Settings()  # type: ignore[call-arg]
    assert settings.MONGO_URI == "mongodb://localhost:27017"
    assert settings.MONGO_DB_NAME == "pdp"
    assert settings.MONGO_CHAIN_TTL_DAYS == 30


def test_env_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@h:1/d")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg://x:y@h:1/d")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("LIVE", "true")
    s = _reload_settings_module()
    settings = s.Settings()  # type: ignore[call-arg]
    assert settings.LIVE is True
    assert "postgresql" in settings.DATABASE_URL
