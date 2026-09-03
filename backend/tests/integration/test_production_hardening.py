"""Regression coverage for the Phase 8 hardening findings.

Every test here corresponds to a defect that was reproduced against a running server
before it was fixed. They are grouped by the bug they lock down, and each names the
failure mode rather than merely asserting the happy path.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import RefreshToken


class TestRefreshTokenReuseDetectionPersists:
    """P0 — the §6 theft response was being rolled back.

    `AuthService.refresh` revoked the family and then raised; `get_db` rolls back on
    any exception, so the revocation never committed. Reuse returned 401 while every
    token in the family stayed alive — the mitigation existed on paper only.
    """

    async def test_presenting_a_rotated_token_kills_the_whole_family(
        self, client, db_session: AsyncSession
    ) -> None:
        registered = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"reuse-{uuid.uuid4().hex[:8]}@example.com",
                    "password": "hunter2222",
                    "display_name": "Reuse",
                },
            )
        ).json()
        user_id = uuid.UUID(registered["user_id"])
        original = registered["refresh_token"]

        rotated = (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
        ).json()["refresh_token"]

        reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
        assert reuse.status_code == 401
        assert reuse.json()["code"] == "REFRESH_REUSE_DETECTED"

        # The legitimate holder's *current* token must also be dead — that is the whole
        # point of family revocation, and what previously kept working.
        after = await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated})
        assert after.status_code == 401, "family revocation did not persist"

        rows = (
            await db_session.execute(
                select(RefreshToken).where(RefreshToken.user_id == user_id)
            )
        ).scalars().all()
        assert rows, "expected refresh tokens for this user"
        assert all(row.revoked_at is not None for row in rows)

    async def test_a_stolen_token_cannot_outlive_detection(self, client) -> None:
        """The attacker's copy is refused on its next use, not merely on the first."""
        registered = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"theft-{uuid.uuid4().hex[:8]}@example.com",
                    "password": "hunter2222",
                    "display_name": "Theft",
                },
            )
        ).json()
        stolen = registered["refresh_token"]
        await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        assert (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        ).status_code == 401


class TestRefreshRotationIsAtomic:
    """P1 — two simultaneous refreshes both minted tokens from one presentation.

    Both read `revoked_at IS NULL` before either wrote, so rotation silently produced
    two live tokens and reuse detection could be raced past entirely.
    """

    async def test_concurrent_refreshes_produce_exactly_one_winner(self, live_client) -> None:  # type: ignore[no-untyped-def]
        registered = (
            await live_client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"race-{uuid.uuid4().hex[:8]}@example.com",
                    "password": "hunter2222",
                    "display_name": "Race",
                },
            )
        ).json()
        live_client.created_users.append(uuid.UUID(registered["user_id"]))
        token = registered["refresh_token"]

        responses = await asyncio.gather(
            *(
                live_client.post("/api/v1/auth/refresh", json={"refresh_token": token})
                for _ in range(5)
            )
        )

        statuses = [r.status_code for r in responses]
        assert statuses.count(200) == 1, f"expected one winner, got {statuses}"
        assert all(
            r.json()["code"] == "REFRESH_REUSE_DETECTED"
            for r in responses
            if r.status_code != 200
        )


class TestChallengeInputValidation:
    """P1 — two unhandled exceptions reachable from a plain request body."""

    async def test_an_oversized_target_is_a_client_error_not_a_500(
        self, client, register_actor, create_group
    ) -> None:
        """`Decimal.quantize` raised InvalidOperation in the service: the schema had no
        `max_digits`, so a 40-digit value reached NUMERIC(12,2) arithmetic."""
        actor = await register_actor(client, "Oversize")
        group = await create_group(client, actor)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/challenges",
            json={
                "name": "BIG", "activity_type": "steps", "target_value": "9" * 40,
                "unit": "steps", "game_mode": "survival",
                "verification_method": "apple_health", "duration_days": 30,
            },
            headers=actor.headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_an_oversized_target_is_also_rejected_on_edit(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor = await register_actor(client, "Oversize2")
        group = await create_group(client, actor)
        challenge = (
            await create_challenge(
                client, actor, group["id"],
                start_at=(datetime(2099, 1, 1, tzinfo=UTC)).isoformat(),
            )
        ).json()

        response = await client.patch(
            f"/api/v1/challenges/{challenge['id']}",
            json={"target_value": "9" * 40},
            headers=actor.headers,
        )

        assert response.status_code == 422

    async def test_a_naive_start_at_is_rejected_rather_than_crashing(
        self, client, register_actor, create_group
    ) -> None:
        """The service compares `start_at` to an aware `now`; a naive value raised
        TypeError and surfaced as a 500."""
        actor = await register_actor(client, "Naive")
        group = await create_group(client, actor)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/challenges",
            json={
                "name": "NAIVE", "activity_type": "steps", "target_value": "10000",
                "unit": "steps", "game_mode": "survival",
                "verification_method": "apple_health", "duration_days": 30,
                "start_at": "2027-01-01T00:00:00",
            },
            headers=actor.headers,
        )

        assert response.status_code == 422
        assert "offset" in response.text.lower()

    async def test_an_aware_start_at_is_still_accepted(
        self, client, register_actor, create_group
    ) -> None:
        actor = await register_actor(client, "Aware")
        group = await create_group(client, actor)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/challenges",
            json={
                "name": "AWARE", "activity_type": "steps", "target_value": "10000",
                "unit": "steps", "game_mode": "survival",
                "verification_method": "apple_health", "duration_days": 30,
                "start_at": "2027-01-01T00:00:00Z",
            },
            headers=actor.headers,
        )

        assert response.status_code == 201


class TestChatContentValidation:
    """P2 — `min_length=1` counts characters, so a whitespace-only message persisted."""

    async def test_a_whitespace_only_message_is_rejected(
        self, client, register_actor, create_group
    ) -> None:
        actor = await register_actor(client, "Blank")
        group = await create_group(client, actor)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/messages",
            json={"content": "   \t\n  "},
            headers=actor.headers,
        )

        assert response.status_code == 422

    async def test_surrounding_whitespace_is_stripped_not_stored(
        self, client, register_actor, create_group
    ) -> None:
        actor = await register_actor(client, "Padded")
        group = await create_group(client, actor)

        body = (
            await client.post(
                f"/api/v1/groups/{group['id']}/messages",
                json={"content": "  hello  "},
                headers=actor.headers,
            )
        ).json()

        assert body["content"] == "hello"


class TestProductionConfigGuard:
    """P1 — nothing stopped a production deployment running with debug on or the
    example JWT secret, either of which is a full compromise."""

    def _settings(self, monkeypatch, **env: str):
        from app.core import config

        for key, value in env.items():
            monkeypatch.setenv(key, value)
        # The sub-settings read `.env.local` as a fallback; the explicit env vars above
        # take precedence, which is what production deployment looks like.
        return config.Settings

    def test_production_refuses_debug_mode(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "true")
        monkeypatch.setenv("AUTH_JWT_SECRET", "b" * 64)

        with pytest.raises(UnsafeProductionConfigError, match="APP_DEBUG"):
            Settings()

    def test_production_refuses_the_placeholder_secret(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "local-dev-only-secret-change-me-please-1234567890")

        with pytest.raises(UnsafeProductionConfigError, match="AUTH_JWT_SECRET"):
            Settings()

    def test_production_refuses_a_short_secret(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "short")

        with pytest.raises(UnsafeProductionConfigError, match="at least"):
            Settings()

    def test_production_refuses_fail_open_rate_limiting(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "c" * 64)
        monkeypatch.setenv("RATE_LIMIT_FAIL_OPEN", "true")

        with pytest.raises(UnsafeProductionConfigError, match="FAIL_OPEN"):
            Settings()

    def test_production_refuses_disabled_rate_limiting(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "d" * 64)
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

        with pytest.raises(UnsafeProductionConfigError, match="RATE_LIMIT_ENABLED"):
            Settings()

    def test_production_refuses_wildcard_cors(self, monkeypatch) -> None:
        from app.core.config import Settings, UnsafeProductionConfigError

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "e" * 64)
        monkeypatch.setenv("APP_CORS_ORIGINS", '["*"]')

        with pytest.raises(UnsafeProductionConfigError, match="CORS"):
            Settings()

    def test_a_correctly_configured_production_env_boots(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "f" * 64)
        monkeypatch.setenv("APP_CORS_ORIGINS", '["https://app.fitwar.example"]')
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("RATE_LIMIT_FAIL_OPEN", "false")

        settings = Settings()
        assert settings.app.is_production
        assert not settings.app.debug

    def test_local_development_is_unaffected(self, monkeypatch) -> None:
        """The guard must not make local dev harder — that is how guards get disabled."""
        from app.core.config import Settings

        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("APP_DEBUG", "true")
        monkeypatch.setenv("AUTH_JWT_SECRET", "local-dev-only-secret-change-me")

        settings = Settings()
        assert not settings.app.is_production


class TestMediaCleanupFailureHandling:
    """P2 — a failed storage delete was recorded as a successful one.

    `run_cleanup` called `storage.delete()`, which swallowed every `ClientError` and
    returned None, then unconditionally set `status=EXPIRED` and `object_deleted_at`.
    The bytes stayed in the bucket forever behind metadata claiming they were gone, and
    nothing ever retried them — despite the docstring promising exactly that.
    """

    async def _expired_asset(self, db_session: AsyncSession, owner_id: uuid.UUID):
        from datetime import timedelta

        from app.models.media import MediaAsset, MediaContextType, MediaStatus

        asset = MediaAsset(
            owner_id=owner_id,
            storage_key=f"verification_proof/{owner_id}/{uuid.uuid4()}.mp4",
            content_type="video/mp4",
            context_type=MediaContextType.VERIFICATION_PROOF,
            status=MediaStatus.PROCESSED,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add(asset)
        await db_session.flush()
        return asset

    async def test_a_failed_delete_leaves_the_row_for_the_next_pass(
        self, client, register_actor, db_session: AsyncSession
    ) -> None:
        from app.models.media import MediaStatus
        from app.services.media_service import MediaService

        actor = await register_actor(client, "CleanupFail")
        asset = await self._expired_asset(db_session, actor.user_id)

        service = MediaService(db_session)

        class RefusingStorage:
            def __init__(self) -> None:
                self.calls = 0

            def delete(self, *, key: str) -> bool:
                self.calls += 1
                return False

        refusing = RefusingStorage()
        service._storage = refusing  # type: ignore[assignment]
        deleted = await service.run_cleanup()

        assert deleted == 0, "a delete that failed must not be counted"
        await db_session.refresh(asset)
        assert asset.object_deleted_at is None, "row was marked deleted despite failure"
        assert asset.status is MediaStatus.PROCESSED
        assert refusing.calls >= 1

    async def test_the_retry_on_the_next_pass_succeeds(
        self, client, register_actor, db_session: AsyncSession
    ) -> None:
        from app.models.media import MediaStatus
        from app.services.media_service import MediaService

        actor = await register_actor(client, "CleanupRetry")
        asset = await self._expired_asset(db_session, actor.user_id)
        service = MediaService(db_session)

        class FlakyStorage:
            def __init__(self) -> None:
                self.attempts = 0

            def delete(self, *, key: str) -> bool:
                self.attempts += 1
                return self.attempts > 1  # fails once, then succeeds

        storage = FlakyStorage()
        service._storage = storage  # type: ignore[assignment]

        assert await service.run_cleanup() == 0
        assert await service.run_cleanup() == 1
        await db_session.refresh(asset)
        assert asset.status is MediaStatus.EXPIRED
        assert asset.object_deleted_at is not None

    async def test_one_failure_does_not_abort_the_rest_of_the_batch(
        self, client, register_actor, db_session: AsyncSession
    ) -> None:
        from app.services.media_service import MediaService

        actor = await register_actor(client, "CleanupBatch")
        bad = await self._expired_asset(db_session, actor.user_id)
        good = await self._expired_asset(db_session, actor.user_id)
        service = MediaService(db_session)

        class SelectiveStorage:
            def delete(self, *, key: str) -> bool:
                return key != bad.storage_key

        service._storage = SelectiveStorage()  # type: ignore[assignment]
        deleted = await service.run_cleanup()

        await db_session.refresh(bad)
        await db_session.refresh(good)
        assert deleted >= 1
        assert bad.object_deleted_at is None
        assert good.object_deleted_at is not None

    async def test_a_pending_review_proof_is_never_swept(
        self, client, register_actor, db_session: AsyncSession
    ) -> None:
        """The mandatory rule: a NULL deadline is structurally excluded."""
        from app.services.media_service import MediaService

        actor = await register_actor(client, "CleanupPending")
        asset = await self._expired_asset(db_session, actor.user_id)
        asset.expires_at = None
        await db_session.flush()

        service = MediaService(db_session)

        seen: list[str] = []

        class AlwaysDeletes:
            def delete(self, *, key: str) -> bool:
                seen.append(key)
                return True

        service._storage = AlwaysDeletes()  # type: ignore[assignment]
        await service.run_cleanup()

        assert asset.storage_key not in seen
        await db_session.refresh(asset)
        assert asset.object_deleted_at is None


class TestStorageDeleteContract:
    """The transport-failure path the cleanup fix depends on."""

    def test_a_transport_failure_reports_false_rather_than_raising(self) -> None:
        """`BotoCoreError` (an unreachable endpoint) is not a `ClientError`. Letting it
        escape aborted the entire sweep on the first unreachable object."""
        from botocore.exceptions import EndpointConnectionError

        from app.integrations.storage.s3 import S3ObjectStorage

        storage = S3ObjectStorage.__new__(S3ObjectStorage)
        storage._bucket = "b"  # type: ignore[attr-defined]

        class BrokenClient:
            def delete_object(self, **_: object) -> None:
                raise EndpointConnectionError(endpoint_url="http://unreachable")

        storage._client = BrokenClient()  # type: ignore[attr-defined]
        assert storage.delete(key="k") is False

    def test_a_successful_delete_reports_true(self) -> None:
        from app.integrations.storage.s3 import S3ObjectStorage

        storage = S3ObjectStorage.__new__(S3ObjectStorage)
        storage._bucket = "b"  # type: ignore[attr-defined]

        class OkClient:
            def delete_object(self, **_: object) -> dict[str, object]:
                return {}

        storage._client = OkClient()  # type: ignore[attr-defined]
        assert storage.delete(key="k") is True


class TestDevEmailSenderCannotRunInProduction:
    """P2 — the no-provider fallback logs raw password-reset tokens.

    `AuthService` defaults to `LoggingEmailSender`, so a deployment that simply never
    configured a provider would have written live reset tokens into its log stream. That
    is account takeover for anyone who can read logs, and nothing prevented it.
    """

    def test_it_refuses_to_construct_in_production(self, monkeypatch) -> None:
        from app.core.config import get_settings
        from app.integrations.email.logging_sender import (
            EmailProviderNotConfiguredError,
            LoggingEmailSender,
        )

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("APP_DEBUG", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "a" * 64)
        # `get_settings` is process-cached (correct in production, where env is fixed at
        # boot), so the cache has to be dropped for the env above to take effect.
        get_settings.cache_clear()
        try:
            with pytest.raises(
                EmailProviderNotConfiguredError, match="never run in production"
            ):
                LoggingEmailSender()
        finally:
            get_settings.cache_clear()

    def test_it_still_works_for_local_development(self, monkeypatch) -> None:
        from app.core.config import get_settings
        from app.integrations.email.logging_sender import LoggingEmailSender

        monkeypatch.setenv("APP_ENV", "local")
        get_settings.cache_clear()
        try:
            assert LoggingEmailSender() is not None
        finally:
            get_settings.cache_clear()

    async def test_a_reset_token_never_reaches_the_response_body(self, client) -> None:
        """Whatever the transport, the token must not come back over HTTP."""
        email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "hunter2222", "display_name": "Reset"},
        )

        response = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )

        assert response.status_code == 202
        assert "token" not in response.text.lower()


class TestRosterQueryScaling:
    """P2 — `GET /groups/{id}/members` was an N+1.

    It called `active_challenge_ids_for_group_member` once per member: 9 statements for
    3 members, 31 for 25. The assertion is on *scaling*, not an absolute count, because
    an absolute number would break on any unrelated query change while still letting a
    real N+1 back in.
    """

    async def _group_with(self, client, register_actor, create_group, join_group, size: int):  # type: ignore[no-untyped-def]
        owner = await register_actor(client, "RosterOwner")
        group = await create_group(client, owner)
        for index in range(size - 1):
            member = await register_actor(client, f"RosterM{index}")
            assert (await join_group(client, member, group["join_code"])).status_code == 200
        return owner, group

    async def test_statement_count_does_not_grow_with_squad_size(
        self, client, register_actor, create_group, join_group
    ) -> None:
        from sqlalchemy import event

        from app.core.database import _engine

        counter = {"n": 0, "on": False}

        def _before(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
            if counter["on"]:
                counter["n"] += 1

        event.listen(_engine.sync_engine, "before_cursor_execute", _before)
        try:
            # Kept under the register-per-IP budget: two sizes far enough apart that a
            # 1-per-member query is unmissable, without needing a dozen accounts.
            small_owner, small = await self._group_with(
                client, register_actor, create_group, join_group, 2
            )
            large_owner, large = await self._group_with(
                client, register_actor, create_group, join_group, 7
            )

            async def measure(owner, group) -> int:
                counter["n"] = 0
                counter["on"] = True
                response = await client.get(
                    f"/api/v1/groups/{group['id']}/members", headers=owner.headers
                )
                counter["on"] = False
                assert response.status_code == 200
                return counter["n"]

            small_count = await measure(small_owner, small)
            large_count = await measure(large_owner, large)
        finally:
            event.remove(_engine.sync_engine, "before_cursor_execute", _before)

        assert large_count == small_count, (
            f"roster query count grew with membership: {small_count} -> {large_count}"
        )

    async def test_the_roster_still_reports_per_member_challenge_counts(
        self, client, register_actor, create_group, join_group, create_challenge
    ) -> None:
        """The N+1 fix must not change what the endpoint actually says."""
        owner = await register_actor(client, "CountOwner")
        group = await create_group(client, owner)
        member = await register_actor(client, "CountMember")
        assert (await join_group(client, member, group["join_code"])).status_code == 200

        challenge = (await create_challenge(client, owner, group["id"])).json()
        assert (
            await client.post(
                f"/api/v1/challenges/{challenge['id']}/join", headers=member.headers
            )
        ).status_code == 201

        roster = (
            await client.get(f"/api/v1/groups/{group['id']}/members", headers=owner.headers)
        ).json()

        by_user = {row["user_id"]: row["active_challenge_count"] for row in roster}
        assert by_user[str(owner.user_id)] == 1
        assert by_user[str(member.user_id)] == 1

    async def test_a_member_in_no_challenge_reports_zero(
        self, client, register_actor, create_group, join_group
    ) -> None:
        owner = await register_actor(client, "ZeroOwner")
        group = await create_group(client, owner)
        member = await register_actor(client, "ZeroMember")
        assert (await join_group(client, member, group["join_code"])).status_code == 200

        roster = (
            await client.get(f"/api/v1/groups/{group['id']}/members", headers=owner.headers)
        ).json()

        assert {row["active_challenge_count"] for row in roster} == {0}
