"""POST /challenges/{id}/verify — contract, idempotency, and authorization."""

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient


async def _active_challenge(client, register_actor, create_group, create_challenge, **overrides):  # type: ignore[no-untyped-def]
    """A challenge that is ACTIVE today, with its creator already a participant."""
    actor = await register_actor(client, "Runner")
    group = await create_group(client, actor)
    response = await create_challenge(client, actor, group["id"], **overrides)
    assert response.status_code == 201, response.text
    return actor, response.json()


async def _today(client: AsyncClient, actor, challenge_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    response = await client.get(
        f"/api/v1/challenges/{challenge_id}/progress/today", headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _evidence(day: dict[str, Any], value: str, **overrides: Any) -> dict[str, Any]:
    """Evidence spanning exactly the server-published window for the challenge day.

    The client is expected to use these bounds verbatim rather than deriving a day from
    its own calendar — that is the whole point of publishing them.
    """
    payload = {
        "metric": "steps",
        "value": value,
        "unit": "steps",
        "period_start": day["window_start_at"],
        "period_end": datetime.now(UTC).isoformat(),
        "source_name": "iPhone",
        "source_bundle_id": "com.apple.health",
        "was_user_entered": False,
    }
    payload.update(overrides)
    return payload


async def _submit(client, actor, challenge_id, evidence, provider="apple_health"):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/verify",
        json={"provider": provider, "evidence": evidence},
        headers=actor.headers,
    )


class TestSuccessfulVerification:
    async def test_meeting_the_target_completes_the_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client, actor, challenge["id"], _evidence(day, "12000")
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verification"]["status"] == "verified"
        assert body["day_status"] == "completed"
        assert body["idempotent_replay"] is False
        assert body["verification"]["target"] == "10000.00"

    async def test_completion_is_visible_on_the_progress_endpoint(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The server is the source of truth — the day reads completed on re-fetch."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        await _submit(client, actor, challenge["id"], _evidence(day, "12000"))

        after = await _today(client, actor, challenge["id"])

        assert after["status"] == "completed"
        assert after["completed_at"] is not None

    async def test_falling_short_leaves_the_day_open(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """A partial sync must not burn the day — a later sync can still complete it."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(client, actor, challenge["id"], _evidence(day, "4000"))

        assert response.status_code == 200
        body = response.json()
        assert body["verification"]["status"] == "inconclusive"
        assert body["verification"]["reason_code"] == "TARGET_NOT_MET"
        assert body["day_status"] == "pending"

    async def test_a_later_sync_can_still_complete_a_short_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        await _submit(client, actor, challenge["id"], _evidence(day, "4000"))

        response = await _submit(client, actor, challenge["id"], _evidence(day, "11000"))

        assert response.json()["day_status"] == "completed"

    async def test_hand_entered_data_never_completes_the_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """Typing 50,000 steps into the Health app must not win a challenge."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client, actor, challenge["id"], _evidence(day, "50000", was_user_entered=True)
        )

        body = response.json()
        assert body["verification"]["status"] == "inconclusive"
        assert body["verification"]["reason_code"] == "USER_ENTERED_DATA"
        assert body["day_status"] == "pending"


class TestIdempotency:
    async def test_resubmitting_a_completed_day_returns_the_original_result(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """A retry after a flaky network must not create a second completion."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        first = await _submit(client, actor, challenge["id"], _evidence(day, "12000"))

        second = await _submit(client, actor, challenge["id"], _evidence(day, "12000"))

        assert second.status_code == 200
        assert second.json()["idempotent_replay"] is True
        # Same record, not a new one — no duplicate state transition.
        assert second.json()["verification"]["id"] == first.json()["verification"]["id"]

    async def test_a_higher_value_cannot_overwrite_a_completed_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        first = await _submit(client, actor, challenge["id"], _evidence(day, "12000"))

        second = await _submit(client, actor, challenge["id"], _evidence(day, "99000"))

        assert second.json()["verification"]["id"] == first.json()["verification"]["id"]
        assert second.json()["verification"]["value"] == "12000.00"


class TestEvidenceRejection:
    async def test_rejects_a_metric_the_challenge_does_not_measure(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client, actor, challenge["id"], _evidence(day, "12", metric="distance", unit="km")
        )

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_EVIDENCE"

    async def test_rejects_an_unsupported_unit(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client, actor, challenge["id"], _evidence(day, "12000", unit="furlongs")
        )

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_EVIDENCE"

    async def test_rejects_evidence_from_another_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The timezone protection, end to end: yesterday's steps can't buy today."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()

        response = await _submit(
            client,
            actor,
            challenge["id"],
            _evidence(day, "12000", period_start=yesterday, period_end=yesterday),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_EVIDENCE"

    async def test_rejects_a_naive_timestamp(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """No UTC offset means no defined instant — guessing one is the device-local
        assumption the timezone rule forbids."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client,
            actor,
            challenge["id"],
            _evidence(day, "12000", period_end="2026-03-11T10:00:00"),
        )

        assert response.status_code == 422

    async def test_rejects_a_provider_the_challenge_does_not_use(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client,
            register_actor,
            create_group,
            create_challenge,
            activity_type="pushups",
            unit="reps",
            verification_method="manual_proof",
        )
        day = await _today(client, actor, challenge["id"])

        response = await _submit(
            client, actor, challenge["id"], _evidence(day, "50", metric="pushups", unit="reps")
        )

        assert response.status_code == 409
        assert response.json()["code"] == "VERIFICATION_METHOD_MISMATCH"


class TestAuthorization:
    async def test_requires_authentication(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/verify",
            json={"provider": "apple_health", "evidence": _evidence(day, "12000")},
        )

        assert response.status_code == 401

    async def test_a_non_participant_cannot_verify(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """Holding a challenge id is not permission to submit against it."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])
        outsider = await register_actor(client, "Outsider")

        response = await _submit(client, outsider, challenge["id"], _evidence(day, "12000"))

        assert response.status_code == 403

    async def test_verifying_an_unknown_challenge_is_not_a_leak(
        self, client, register_actor
    ) -> None:
        """A stranger's challenge id must not be distinguishable from a missing one."""
        actor = await register_actor(client, "Prober")
        unknown = "00000000-0000-0000-0000-000000000000"

        response = await client.post(
            f"/api/v1/challenges/{unknown}/verify",
            json={
                "provider": "apple_health",
                "evidence": {
                    "metric": "steps",
                    "value": "1",
                    "unit": "steps",
                    "period_start": datetime.now(UTC).isoformat(),
                    "period_end": datetime.now(UTC).isoformat(),
                },
            },
            headers=actor.headers,
        )

        assert response.status_code in (403, 404)
        assert "steps" not in response.text.lower() or response.status_code == 404


class TestContract:
    async def test_response_carries_the_full_documented_shape(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )
        day = await _today(client, actor, challenge["id"])

        body = (await _submit(client, actor, challenge["id"], _evidence(day, "12000"))).json()

        assert set(body) == {
            "verification",
            "challenge_day",
            "day_status",
            "deadline_at",
            "idempotent_replay",
            "resolution",
        }
        # Phase 5: a completed day reports what it earned, all server-computed.
        assert set(body["resolution"]) == {
            "xp_awarded",
            "completion_xp",
            "streak_bonus_xp",
            "score_delta",
            "current_streak",
        }
        assert set(body["verification"]) == {
            "id",
            "provider",
            "metric",
            "value",
            "target",
            "status",
            "reason_code",
            "source_timestamp",
            "verified_at",
        }

    async def test_progress_publishes_both_bounds_of_the_day(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The client needs the start too: a DST day isn't 24h, so it can't be derived."""
        actor, challenge = await _active_challenge(
            client, register_actor, create_group, create_challenge
        )

        day = await _today(client, actor, challenge["id"])

        assert day["window_start_at"] < day["deadline_at"]
