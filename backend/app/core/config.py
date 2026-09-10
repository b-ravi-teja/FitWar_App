"""Typed configuration, composed from one pydantic-settings class per domain.

Each sub-settings class reads its own env-var prefix independently, so `Settings`
is a plain composition — instantiating it fails fast (raises `pydantic.ValidationError`)
if any required environment variable is missing or malformed, which is exactly what
should happen before the app is allowed to accept a single request.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# libpq's `sslmode` values, mapped onto the ones asyncpg's `ssl` argument accepts.
# `allow` has no asyncpg equivalent and is the weaker half of libpq's two "try TLS,
# fall back" modes, so it maps to `prefer` rather than being dropped.
_SSLMODE_TO_ASYNCPG_SSL = {
    "disable": "disable",
    "allow": "prefer",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}

# Query parameters libpq understands and asyncpg does not. Left in the URI they reach
# `asyncpg.connect()` as unexpected keyword arguments and raise `TypeError` on the first
# connection — a failure that looks nothing like "your connection string has a psql-only
# option in it". `pgbouncer=true` is Prisma's marker, which managed providers sometimes
# include in a copy-pasted pooler URI.
_DROPPED_LIBPQ_PARAMS = frozenset(
    {
        "sslrootcert",
        "sslcert",
        "sslkey",
        "channel_binding",
        "options",
        "pgbouncer",
        "application_name",
        "connect_timeout",
        "target_session_attrs",
    }
)


def normalize_asyncpg_dsn(dsn: str) -> str:
    """Rewrite a libpq-style Postgres URI into one SQLAlchemy's asyncpg dialect accepts.

    Managed Postgres dashboards hand out `postgresql://…?sslmode=require` — psql's
    syntax. This translates the scheme and the TLS option rather than asking every
    deployment to hand-edit a string it was told to copy verbatim.

    `sslmode` is translated, never dropped: dropping it would silently downgrade a
    connection the operator asked to encrypt into a plaintext one, and nothing would
    report that it happened.
    """
    parts = urlsplit(dsn.strip())

    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered == "sslmode":
            translated = _SSLMODE_TO_ASYNCPG_SSL.get(value.lower())
            if translated is not None:
                params.append(("ssl", translated))
            continue
        if lowered in _DROPPED_LIBPQ_PARAMS:
            continue
        params.append((key, value))

    return urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
    )


class DatabaseSettings(BaseSettings):
    """Postgres connection, from either a full URI or discrete parts.

    Managed Postgres (Supabase, Neon, RDS) hands out a single connection URI, so
    `DATABASE_URL` is accepted verbatim and wins when set. Re-typing its five components
    into separate variables is how a password with a `@` in it silently produces a
    connection to the wrong host. The discrete variables remain for Compose and CI,
    where the parts are known and no URI exists to copy.
    """

    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=".env.local", extra="ignore")

    # Explicit alias: with `env_prefix="DATABASE_"` a field named `url_override` would
    # otherwise read DATABASE_URL_OVERRIDE, and `url` is taken by the property below.
    url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")

    host: str | None = None
    port: int = 5432
    user: str | None = None
    password: SecretStr | None = None
    name: str | None = None

    pool_size: int = 5
    # Connections the pool may open *beyond* pool_size under load. Managed Postgres
    # bills and caps by connection count, so a deployment behind a shared pooler sets
    # this to 0 to make the ceiling exactly pool_size instead of pool_size + 10.
    max_overflow: int = 10

    # asyncpg prepares statements by default, which a connection pooler in *transaction*
    # mode cannot support — the prepared statement is created on one backend and reused
    # on another, surfacing as `InvalidSQLStatementNameError` under concurrency rather
    # than at startup. Session-mode pooling and direct connections are unaffected, so
    # this stays off; it is the escape hatch for a deployment that has no session-mode
    # option. See docs/DEPLOYMENT.md.
    disable_prepared_statements: bool = False

    @model_validator(mode="after")
    def _require_a_connection_source(self) -> "DatabaseSettings":
        if self.url_override:
            return self
        missing = [
            f"DATABASE_{part.upper()}"
            for part in ("host", "user", "password", "name")
            if getattr(self, part) is None
        ]
        if missing:
            raise ValueError(
                "Set DATABASE_URL, or all of " + ", ".join(missing) + "."
            )
        return self

    @property
    def url(self) -> str:
        if self.url_override:
            return normalize_asyncpg_dsn(self.url_override)
        assert self.password is not None  # guaranteed by _require_a_connection_source
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
    """S3-compatible object storage config (MinIO locally, AWS S3 or Cloudflare R2 deployed)."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_", env_file=".env.local", extra="ignore")

    endpoint_url: str
    region: str
    bucket_name: str
    access_key_id: str
    secret_access_key: SecretStr

    # How a client uploads: a policy-signed multipart POST, or a signed PUT.
    #
    # POST is the better of the two and stays the default — its policy pins a
    # content-length range, so storage rejects an oversized upload at the edge and the
    # bytes are never stored. R2 does not implement S3 PostObject (its presigned URLs
    # are GET/PUT/HEAD/DELETE only), so an R2 deployment sets this to "put" and the
    # size ceiling is enforced by the server at complete-upload instead. That check runs
    # for both modes — see `MediaService.complete_upload`.
    upload_method: Literal["post", "put"] = "post"

    # Virtual-host addressing puts the bucket in the hostname; path-style puts it in the
    # path. MinIO needs path-style, S3 and R2 accept either, so path-style is the default
    # that works everywhere.
    addressing_style: Literal["path", "virtual"] = "path"


class EmailSettings(BaseSettings):
    """Transactional email (ADR 0007). FITWAR sends exactly one kind: the password-reset
    code.

    `logging` is the local default and writes the code to the log instead of sending it —
    `LoggingEmailSender` refuses to construct in a production environment, so a staging
    deployment that forgets to set a provider fails loudly instead of quietly writing
    live reset tokens into a log stream.
    """

    model_config = SettingsConfigDict(env_prefix="EMAIL_", env_file=".env.local", extra="ignore")

    provider: Literal["logging", "resend"] = "logging"
    api_key: SecretStr | None = None
    # Must be an address on a domain verified with the provider, or delivery is refused.
    from_address: str = "FITWAR <onboarding@resend.dev>"
    # Short: the caller holds a request open while this runs, and a slow provider must
    # not become a slow API.
    timeout_seconds: float = 10.0


# Environments that must not run with development affordances enabled.
PRODUCTION_ENVS = frozenset({"production", "prod", "staging"})

# Placeholder secrets that ship in `.env.example`. Present in a production environment
# they mean nobody generated a real one — and a known JWT secret is a full
# authentication bypass, since anyone can mint an access token for any user id.
_PLACEHOLDER_SECRET_MARKERS = ("change-me", "changeme", "local-dev", "example", "placeholder")
MIN_JWT_SECRET_LENGTH = 32


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env.local", extra="ignore")

    env: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENVS


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


class UnsafeProductionConfigError(RuntimeError):
    """A configuration that is fine locally and unacceptable in production.

    Raised at construction, so the process refuses to start rather than serving
    traffic in a state nobody would have chosen deliberately.
    """


class SchedulerSettings(BaseSettings):
    """Periodic background jobs (Architecture §35).

    Intervals are environment-configurable so a deployment can tune them without a code
    change, and `disabled_jobs` exists so a platform that schedules the same work
    natively (a Kubernetes CronJob, an ECS scheduled task) can turn off the in-process
    runner without deleting it.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_", env_file=".env.local", extra="ignore"
    )

    # Deadlines are per-challenge-day boundaries, so resolving every few minutes is far
    # finer than the rule needs while keeping "you were eliminated" close to the moment
    # it became true.
    deadline_sweep_interval_seconds: int = 300
    # Retention is measured in hours (§33), so hourly is ample and keeps storage calls
    # rare.
    media_cleanup_interval_seconds: int = 3600
    disabled_jobs: set[str] = Field(default_factory=set)


class Settings:
    """Single composition root. Construct once via `get_settings()`."""

    def __init__(self) -> None:
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.auth = AuthSettings()
        self.storage = StorageSettings()
        self.email = EmailSettings()
        self.media = MediaSettings()
        self.app = ApplicationSettings()
        self.rate_limit = RateLimitSettings()
        self.scheduler = SchedulerSettings()
        self._assert_safe_for_environment()

    def _assert_safe_for_environment(self) -> None:
        """Fail fast on development defaults that are dangerous in production.

        Each of these is a real failure mode rather than a policy preference:

        - `debug=True` makes Starlette's ServerErrorMiddleware render a full traceback
          to the *client* on any unhandled exception — and it does so instead of the
          registered handler, so the Problem Details envelope never runs. That leaks
          file paths, library versions and code context to anyone who can trigger a 500.
        - A placeholder or short `AUTH_JWT_SECRET` means access tokens can be forged for
          any user id: complete authentication bypass, not a hardening nicety.
        - `allow_origins=["*"]` with `allow_credentials=True` is rejected by browsers
          anyway, so it is never what was intended; it silently disables CORS instead.
        - Fail-open rate limiting means an attacker who can degrade Redis also switches
          off brute-force protection (§7).
        """
        if not self.app.is_production:
            return

        problems: list[str] = []
        if self.app.debug:
            problems.append(
                "APP_DEBUG must be false outside local development — debug mode returns "
                "stack traces to clients."
            )

        secret = self.auth.jwt_secret.get_secret_value()
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            problems.append(
                f"AUTH_JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters."
            )
        if any(marker in secret.lower() for marker in _PLACEHOLDER_SECRET_MARKERS):
            problems.append(
                "AUTH_JWT_SECRET still looks like the example placeholder — generate one "
                "with `openssl rand -hex 32`."
            )

        if "*" in self.app.cors_origins:
            problems.append(
                "APP_CORS_ORIGINS must list real origins; '*' with credentials is invalid."
            )

        if self.email.provider == "logging":
            problems.append(
                "EMAIL_PROVIDER must name a real provider outside local development — "
                "the logging sender writes password-reset codes to the log."
            )

        if self.rate_limit.enabled and self.rate_limit.fail_open:
            problems.append(
                "RATE_LIMIT_FAIL_OPEN must be false in production — see Architecture §7."
            )
        if not self.rate_limit.enabled:
            problems.append("RATE_LIMIT_ENABLED must be true in production.")

        if problems:
            raise UnsafeProductionConfigError(
                f"Unsafe configuration for APP_ENV={self.app.env!r}: " + " ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
