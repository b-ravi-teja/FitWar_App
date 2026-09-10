"""Configuration that only ever runs in a deployed environment.

These paths are invisible locally — Compose supplies discrete DATABASE_* variables and
MinIO speaks the full S3 API — so nothing else in the suite would notice them breaking
until a deploy failed. Each test here corresponds to a way a managed provider differs
from the local stack.
"""

import pytest
from pydantic import ValidationError

from app.core.config import DatabaseSettings, normalize_asyncpg_dsn


class TestNormalizeAsyncpgDsn:
    """Managed Postgres dashboards hand out libpq connection strings; SQLAlchemy's
    asyncpg dialect does not accept them unchanged."""

    def test_it_selects_the_asyncpg_driver(self) -> None:
        assert normalize_asyncpg_dsn("postgresql://u:p@h:5432/db").startswith(
            "postgresql+asyncpg://"
        )

    def test_it_upgrades_the_short_postgres_scheme(self) -> None:
        """Some providers emit `postgres://`, which SQLAlchemy rejects outright."""
        assert normalize_asyncpg_dsn("postgres://u:p@h:5432/db").startswith(
            "postgresql+asyncpg://"
        )

    def test_it_leaves_an_explicit_driver_alone(self) -> None:
        dsn = "postgresql+asyncpg://u:p@h:5432/db"
        assert normalize_asyncpg_dsn(dsn) == dsn

    def test_it_translates_sslmode_rather_than_dropping_it(self) -> None:
        """Dropping it would silently downgrade a connection the operator asked to
        encrypt — the failure nobody would ever notice."""
        result = normalize_asyncpg_dsn("postgresql://u:p@h:5432/db?sslmode=require")
        assert "ssl=require" in result
        assert "sslmode" not in result

    @pytest.mark.parametrize(
        ("sslmode", "expected"),
        [
            ("disable", "ssl=disable"),
            ("allow", "ssl=prefer"),
            ("prefer", "ssl=prefer"),
            ("require", "ssl=require"),
            ("verify-ca", "ssl=verify-ca"),
            ("verify-full", "ssl=verify-full"),
        ],
    )
    def test_every_sslmode_maps_to_an_asyncpg_value(self, sslmode: str, expected: str) -> None:
        assert expected in normalize_asyncpg_dsn(f"postgresql://u:p@h/db?sslmode={sslmode}")

    def test_it_drops_parameters_asyncpg_would_reject(self) -> None:
        """Left in place these reach `asyncpg.connect()` as unexpected keyword
        arguments and raise TypeError at the first connection, not at startup."""
        result = normalize_asyncpg_dsn(
            "postgresql://u:p@h/db?pgbouncer=true&channel_binding=require&application_name=x"
        )
        assert "pgbouncer" not in result
        assert "channel_binding" not in result
        assert "application_name" not in result

    def test_it_keeps_parameters_it_does_not_recognise(self) -> None:
        """A denylist, not an allowlist: a future asyncpg option must not need a code
        change here to be usable."""
        assert "some_new_option=1" in normalize_asyncpg_dsn(
            "postgresql://u:p@h/db?some_new_option=1"
        )

    def test_it_preserves_credentials_and_target(self) -> None:
        result = normalize_asyncpg_dsn(
            "postgresql://user.ref:pw%40word@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
            "?sslmode=require"
        )
        assert "user.ref:pw%40word@aws-0-eu-west-1.pooler.supabase.com:5432/postgres" in result


class TestDatabaseSettingsSources:
    def test_database_url_wins_when_set(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@managed.example:5432/db")
        # Present and deliberately different: a deployment that sets both must not end
        # up connecting to a mixture of the two.
        monkeypatch.setenv("DATABASE_HOST", "localhost")
        monkeypatch.setenv("DATABASE_USER", "local")
        monkeypatch.setenv("DATABASE_PASSWORD", "local")
        monkeypatch.setenv("DATABASE_NAME", "local")

        assert "managed.example" in DatabaseSettings().url
        assert "localhost" not in DatabaseSettings().url

    def test_discrete_variables_still_work(self, monkeypatch) -> None:
        """Compose and CI have no URI to copy — they know the parts."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_HOST", "postgres")
        monkeypatch.setenv("DATABASE_PORT", "5432")
        monkeypatch.setenv("DATABASE_USER", "fitwar")
        monkeypatch.setenv("DATABASE_PASSWORD", "pw")
        monkeypatch.setenv("DATABASE_NAME", "fitwar")

        assert DatabaseSettings().url == "postgresql+asyncpg://fitwar:pw@postgres:5432/fitwar"

    def test_neither_source_is_a_startup_error(self, monkeypatch) -> None:
        """Fail at boot naming the missing variables, not on the first request that
        needs a database."""
        for key in ("URL", "HOST", "USER", "PASSWORD", "NAME"):
            monkeypatch.delenv(f"DATABASE_{key}", raising=False)

        with pytest.raises(ValidationError, match="DATABASE_HOST"):
            # `_env_file=None` because the developer running this has a `.env.local`
            # that would otherwise satisfy every one of these.
            DatabaseSettings(_env_file=None)
