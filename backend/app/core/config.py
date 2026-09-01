"""Typed configuration, composed from one pydantic-settings class per domain.

Each sub-settings class reads its own env-var prefix independently, so `Settings`
is a plain composition — instantiating it fails fast (raises `pydantic.ValidationError`)
if any required environment variable is missing or malformed, which is exactly what
should happen before the app is allowed to accept a single request.
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=".env.local", extra="ignore")

    host: str
    port: int = 5432
    user: str
    password: SecretStr
    name: str
    pool_size: int = 5

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env.local", extra="ignore")

    url: str


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env.local", extra="ignore")

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30


class StorageSettings(BaseSettings):
    """S3-compatible object storage config. Not wired to any endpoint until the Media phase."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_", env_file=".env.local", extra="ignore")

    endpoint_url: str
    region: str
    bucket_name: str
    access_key_id: str
    secret_access_key: SecretStr


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env.local", extra="ignore")

    env: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)


class Settings:
    """Single composition root. Construct once via `get_settings()`."""

    def __init__(self) -> None:
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.auth = AuthSettings()
        self.storage = StorageSettings()
        self.app = ApplicationSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
