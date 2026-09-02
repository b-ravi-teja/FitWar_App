"""Challenge API — creation, join/leave, limits, state transitions, daily progress,
and the authorization boundaries around all of it.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient


class TestCreateChallenge:
    async def test_member_can_create_and_is_auto_joined(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)

        response = await create_challenge(client, ravi, group["id"])

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "30 DAY STEP WAR"
        assert body["game_mode"] == "survival"
        assert body["status"] == "active"
        assert body["duration_days"] == 30
        assert body["day_index"] == 1
        assert body["participant_count"] == 1
        assert body["my_status"] == "active"
        assert body["participants"][0]["display_name"] == "Ravi"

    async def test_timezone_is_snapshotted_from_the_group(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi, timezone="America/New_York")

        created = await create_challenge(client, ravi, group["id"])
        assert created.json()["timezone"] == "America/New_York"

    async def test_group_timezone_change_does_not_reach_an_existing_challenge(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        # Architecture §11: an in-flight challenge must keep a stable, non-retroactive
        # daily boundary even if the group is later edited.
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi, timezone="Asia/Kolkata")
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        await client.patch(
            f"/api/v1/groups/{group['id']}",
            json={"timezone": "Europe/London"},
            headers=ravi.headers,
        )

        after = await client.get(
            f"/api/v1/challenges/{challenge['id']}", headers=ravi.headers
        )
        assert after.json()["timezone"] == "Asia/Kolkata"

    async def test_non_member_cannot_create_in_a_group(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)

        response = await create_challenge(client, outsider, group["id"])

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_MEMBER"

    async def test_plain_member_may_create(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        # API_SPEC gates challenge creation on `member`, not admin — Architecture §7's
        # flat role model has no separate create permission.
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        response = await create_challenge(client, sai, group["id"])
        assert response.status_code == 201

    async def test_future_start_creates_a_draft(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        start = (datetime.now(UTC) + timedelta(days=2)).isoformat()

        response = await create_challenge(client, ravi, group["id"], start_at=start)

        assert response.json()["status"] == "draft"

    async def test_client_cannot_choose_the_status(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        # Architecture §1 tenet 1: the client sends configuration, never a resulting
        # state. An extra `status` in the body is ignored, not honoured.
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)

        response = await create_challenge(
            client, ravi, group["id"], status="completed", start_at=None
        )

        assert response.json()["status"] == "active"

    async def test_rejects_a_zero_target(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        response = await create_challenge(client, ravi, group["id"], target_value="0")
        assert response.status_code == 422

    async def test_rejects_an_unbuilt_game_mode(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        # TOURNAMENT/TEAM/BOSS are "SOON" in the design; the API refuses them rather
        # than accepting a value nothing implements.
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        response = await create_challenge(client, ravi, group["id"], game_mode="tournament")
        assert response.status_code == 422

    async def test_points_mode_reports_no_elimination_rule(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        response = await create_challenge(client, ravi, group["id"], game_mode="points")
        assert "ELIMINATED" not in response.json()["failure_rule"]

    async def test_survival_mode_reports_the_two_strike_rule(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        response = await create_challenge(client, ravi, group["id"])
        assert response.json()["failure_rule"] == "MISS TWICE → ELIMINATED"


class TestReadChallenge:
    async def test_group_member_can_view_without_joining(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}", headers=sai.headers
        )

        assert response.status_code == 200
        assert response.json()["my_status"] is None

    async def test_outsider_cannot_view(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}", headers=outsider.headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_PARTICIPANT"

    async def test_unknown_challenge_is_404(
        self, client: AsyncClient, register_actor
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        response = await client.get(
            "/api/v1/challenges/2f9b7e3a-0000-4000-8000-000000000000", headers=ravi.headers
        )
        assert response.status_code == 404
        assert response.json()["code"] == "CHALLENGE_NOT_FOUND"

    async def test_list_mine_filters_by_status(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        await create_challenge(client, ravi, group["id"], name="Live one")
        await create_challenge(
            client,
            ravi,
            group["id"],
            name="Future one",
            start_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        )

        active = await client.get("/api/v1/challenges?status=active", headers=ravi.headers)
        draft = await client.get("/api/v1/challenges?status=draft", headers=ravi.headers)

        assert [c["name"] for c in active.json()] == ["Live one"]
        assert [c["name"] for c in draft.json()] == ["Future one"]

    async def test_list_mine_excludes_challenges_i_did_not_join(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await create_challenge(client, ravi, group["id"])

        response = await client.get("/api/v1/challenges", headers=sai.headers)
        assert response.json() == []


class TestJoinAndLeave:
    async def test_group_member_can_join(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers
        )

        assert response.status_code == 201
        assert response.json()["participant_count"] == 2
        assert response.json()["my_status"] == "active"

    async def test_non_group_member_cannot_join(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=outsider.headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_MEMBER"

    async def test_joining_twice_conflicts(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=ravi.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "ALREADY_JOINED"

    async def test_participant_limit_is_enforced(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        meera = await register_actor(client, "Meera")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await join_group(client, meera, group["join_code"])
        challenge = (
            await create_challenge(client, ravi, group["id"], participant_limit=2)
        ).json()

        first = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers
        )
        second = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=meera.headers
        )

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["code"] == "PARTICIPANT_LIMIT_REACHED"

    async def test_participant_can_leave(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()
        await client.post(f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers)

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/leave", headers=sai.headers
        )

        assert response.status_code == 204
        detail = await client.get(
            f"/api/v1/challenges/{challenge['id']}", headers=sai.headers
        )
        assert detail.json()["my_status"] == "left"
        left = next(
            p for p in detail.json()["participants"] if p["display_name"] == "Sai"
        )
        assert left["outcome"] == "left"

    async def test_leaving_frees_a_slot_but_rejoining_is_refused(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        # Terminal participant states never revive (Architecture §3.3) — otherwise
        # elimination in SURVIVAL would mean nothing.
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()
        await client.post(f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers)
        await client.post(f"/api/v1/challenges/{challenge['id']}/leave", headers=sai.headers)

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CANNOT_REJOIN"

    async def test_non_participant_cannot_leave(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/leave", headers=sai.headers
        )
        assert response.status_code == 403


class TestStateTransitions:
    async def test_draft_can_be_cancelled(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (
            await create_challenge(
                client,
                ravi,
                group["id"],
                start_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
            )
        ).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/cancel", headers=ravi.headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    async def test_active_challenge_cannot_be_cancelled(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/cancel", headers=ravi.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_STATE_TRANSITION"

    async def test_non_creator_member_cannot_cancel(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (
            await create_challenge(
                client,
                ravi,
                group["id"],
                start_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
            )
        ).json()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/cancel", headers=sai.headers
        )
        assert response.status_code == 403

    async def test_draft_can_be_edited_pre_start(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (
            await create_challenge(
                client,
                ravi,
                group["id"],
                start_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
            )
        ).json()

        response = await client.patch(
            f"/api/v1/challenges/{challenge['id']}",
            json={"name": "RENAMED WAR", "target_value": "12000"},
            headers=ravi.headers,
        )

        assert response.status_code == 200
        assert response.json()["name"] == "RENAMED WAR"
        assert response.json()["target_value"] == "12000.00"

    async def test_active_challenge_cannot_be_edited(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.patch(
            f"/api/v1/challenges/{challenge['id']}",
            json={"name": "Too late"},
            headers=ravi.headers,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CHALLENGE_ALREADY_ACTIVE"

    async def test_a_finished_challenge_reports_completed(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        # A one-day challenge started "now" ends at the next local midnight; the status
        # sync promotes it to COMPLETED as soon as that instant passes. Rather than wait,
        # this drives the clock forward through the service the API itself uses.
        from app.core.database import get_db

        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi, timezone="UTC")
        challenge = (
            await create_challenge(client, ravi, group["id"], duration_days=1)
        ).json()
        assert challenge["status"] == "active"

        from app.models.challenge import Challenge
        from app.services.challenge_service import ChallengeService

        session = await anext(client._transport.app.dependency_overrides[get_db]())  # type: ignore[attr-defined]
        service = ChallengeService(session)
        row = await session.get(Challenge, challenge["id"])
        assert row is not None
        await service.sync_status(row, now=datetime.now(UTC) + timedelta(days=3))

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}", headers=ravi.headers
        )
        assert response.json()["status"] == "completed"

    async def test_joining_a_cancelled_challenge_is_refused(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (
            await create_challenge(
                client,
                ravi,
                group["id"],
                start_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
            )
        ).json()
        await client.post(f"/api/v1/challenges/{challenge['id']}/cancel", headers=ravi.headers)

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CHALLENGE_ALREADY_ENDED"


class TestDailyProgress:
    async def test_today_returns_a_pending_row(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/today", headers=ravi.headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["day_index"] == 1
        assert body["target"] == "10000.00"
        assert body["completed_at"] is None
        # No `current_value` field at all — verification is Phase 4, and a zero here
        # would read in the UI as "you've done nothing today", which isn't what
        # PENDING means.
        assert "current_value" not in body

    async def test_today_is_idempotent(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        first = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/today", headers=ravi.headers
        )
        second = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/today", headers=ravi.headers
        )

        assert first.json() == second.json()

    async def test_today_uses_the_challenge_timezone(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi, timezone="Pacific/Kiritimati")  # UTC+14
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/today", headers=ravi.headers
        )

        from zoneinfo import ZoneInfo

        expected = datetime.now(UTC).astimezone(ZoneInfo("Pacific/Kiritimati")).date()
        assert response.json()["challenge_day"] == expected.isoformat()

    async def test_non_participant_cannot_read_progress(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/today", headers=sai.headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_PARTICIPANT"

    async def test_a_date_outside_the_challenge_is_refused(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/2020-01-01",
            headers=ravi.headers,
        )

        assert response.status_code == 404
        assert response.json()["code"] == "DAY_OUT_OF_RANGE"

    async def test_a_historical_date_is_not_backfilled(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        # `/today` creates a row; `/{date}` must not — inventing a record for a day
        # nobody looked at would fabricate history.
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi, timezone="UTC")
        challenge = (await create_challenge(client, ravi, group["id"])).json()
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/progress/{tomorrow}",
            headers=ravi.headers,
        )
        assert response.status_code == 404


class TestParticipantsList:
    async def test_ranks_are_assigned_at_read_time(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        challenge = (await create_challenge(client, ravi, group["id"])).json()
        await client.post(f"/api/v1/challenges/{challenge['id']}/join", headers=sai.headers)

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/participants", headers=ravi.headers
        )

        assert [p["rank"] for p in response.json()] == [1, 2]
        # Every score is genuinely zero until verification exists — no seeded standings.
        assert {p["current_score"] for p in response.json()} == {"0.00"}

    async def test_outsider_cannot_list_participants(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)
        challenge = (await create_challenge(client, ravi, group["id"])).json()

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/participants", headers=outsider.headers
        )
        assert response.status_code == 403


class TestGroupChallengeListing:
    async def test_group_challenges_visible_to_members(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await create_challenge(client, ravi, group["id"])

        response = await client.get(
            f"/api/v1/groups/{group['id']}/challenges", headers=sai.headers
        )

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["my_status"] is None

    async def test_group_active_challenge_count_reflects_reality(
        self, client: AsyncClient, register_actor, create_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        await create_challenge(client, ravi, group["id"])

        response = await client.get(f"/api/v1/groups/{group['id']}", headers=ravi.headers)
        assert response.json()["active_challenge_count"] == 1
