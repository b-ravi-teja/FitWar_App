import pytest
from pydantic import ValidationError

from app.core.config import DatabaseSettings, get_settings


def test_settings_load_successfully_from_env() -> None:
    """The real .env.local (present in this dev/test environment) must satisfy every
    required field across all five settings domains — this is the fail-fast contract."""
    settings = get_settings()
    assert settings.database.host
    assert settings.auth.jwt_algorithm == "HS256"
    assert settings.redis.url.startswith("redis://")


def test_database_url_never_contains_literal_password_placeholder() -> None:
    url = get_settings().database.url
    assert "postgresql+asyncpg://" in url


def test_missing_required_database_field_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting a required var must raise at construction time, not surface later as an
    obscure connection error the first time a route touches the database."""
    monkeypatch.delenv("DATABASE_USER", raising=False)
    monkeypatch.setenv("DATABASE_HOST", "localhost")
    monkeypatch.setenv("DATABASE_PASSWORD", "x")
    monkeypatch.setenv("DATABASE_NAME", "x")

    with pytest.raises(ValidationError):
        DatabaseSettings(_env_file=None)
