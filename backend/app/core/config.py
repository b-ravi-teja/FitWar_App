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

    @property
    def jwt_secret_value(self) -> str:
        return self.jwt_secret.get_secret_value()


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


class RateLimitSettings(BaseSettings):
    """Sliding-window rate limits (Architecture §7).

    Defaults are deliberately generous enough to be invisible to a real person and
    still useless to an attacker: 10 password guesses per 15 minutes against one
    account is not a viable brute force, but no honest user hits it. Registration and
    password-reset are rare actions, so they get hourly budgets; refresh is frequent
    and automatic (every ~15 minutes per signed-in device), so its ceiling is high
    enough to absorb a shared office NAT.
    """

    model_config = SettingsConfigDict(
        env_prefix="RATE_LIMIT_", env_file=".env.local", extra="ignore"
    )

    enabled: bool = True

    # 0 = never trust X-Forwarded-For. Raise it to the number of proxies actually in
    # front of the app once one is deployed; see `client_ip()` for why this matters.
    trusted_proxy_count: int = 0

    # False = fail closed: if Redis is down, throttled endpoints reject rather than
    # run unprotected. See docs/ARCHITECTURE.md §7 for the trade-off.
    fail_open: bool = False

    login_ip_limit: int = 20
    login_ip_window_seconds: int = 300
    login_account_limit: int = 10
    login_account_window_seconds: int = 900

    register_ip_limit: int = 10
    register_ip_window_seconds: int = 3600

    refresh_ip_limit: int = 120
    refresh_ip_window_seconds: int = 300

    password_reset_ip_limit: int = 10
    password_reset_ip_window_seconds: int = 3600
    password_reset_account_limit: int = 5
    password_reset_account_window_seconds: int = 3600


class MediaSettings(BaseSettings):
    """Media limits and the retention policy (Architecture §33).

    Storage cost is an explicit product constraint: FITWAR keeps the competitive record
    forever and the video for hours. Every value here is environment-configurable so a
    deployment can tighten or loosen retention without a code change.
    """

    model_config = SettingsConfigDict(env_prefix="MEDIA_", env_file=".env.local", extra="ignore")

    # Proof video ceiling. Enforced by the presigned POST policy itself, so an oversized
    # upload is rejected by storage rather than discovered afterwards.
    max_proof_bytes: int = 250 * 1024 * 1024
    allowed_video_types: list[str] = Field(
        default_factory=lambda: ["video/mp4", "video/quicktime"]
    )
    # How long a presigned upload grant stays valid.
    upload_url_ttl_seconds: int = 15 * 60
    # How long a signed playback URL stays valid — short, because it grants read access
    # to a private proof.
    download_url_ttl_seconds: int = 5 * 60
    # Hours a video survives after its proof is approved or rejected.
    resolved_retention_hours: int = 24
    # An upload that never becomes a submitted proof is abandoned; it expires far sooner
    # because nothing references it and nobody is waiting on it.
    abandoned_upload_ttl_hours: int = 6


class Settings:
    """Single composition root. Construct once via `get_settings()`."""

    def __init__(self) -> None:
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.auth = AuthSettings()
        self.storage = StorageSettings()
        self.media = MediaSettings()
        self.app = ApplicationSettings()
        self.rate_limit = RateLimitSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
