"""Group API — creation, invite/join, leave, roster, and the authorization boundaries.

The 403/409 cases are tested as seriously as the happy paths: an authorization hole is
a worse defect than a broken feature, because nothing surfaces it.
"""

from httpx import AsyncClient


class TestCreateAndList:
    async def test_create_makes_the_caller_owner(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)

        assert group["name"] == "KITS FITNESS WAR"
        assert group["timezone"] == "Asia/Kolkata"
        assert group["owner_id"] == str(ravi.user_id)
        assert group["my_role"] == "owner"
        assert group["member_count"] == 1
        assert group["active_challenge_count"] == 0
        assert group["privacy"] == "invite"
        assert len(group["join_code"]) == 6

    async def test_rejects_a_non_iana_timezone(
        self, client: AsyncClient, register_actor
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        response = await client.post(
            "/api/v1/groups",
            json={"name": "Bad TZ", "timezone": "UTC+5:30"},
            headers=ravi.headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_TIMEZONE"

    async def test_list_returns_only_the_callers_groups(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        arjun = await register_actor(client, "Arjun")
        await create_group(client, ravi, name="Ravi's Squad")
        await create_group(client, arjun, name="Arjun's Squad")

        response = await client.get("/api/v1/groups", headers=ravi.headers)

        assert response.status_code == 200
        names = [g["name"] for g in response.json()]
        assert names == ["Ravi's Squad"]

    async def test_list_supports_multiple_groups_per_user(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        await create_group(client, ravi, name="Squad A")
        await create_group(client, ravi, name="Squad B")

        response = await client.get("/api/v1/groups", headers=ravi.headers)

        assert {g["name"] for g in response.json()} == {"Squad A", "Squad B"}

    async def test_empty_for_a_user_in_no_groups(
        self, client: AsyncClient, register_actor
    ) -> None:
        loner = await register_actor(client, "Loner")
        response = await client.get("/api/v1/groups", headers=loner.headers)
        assert response.json() == []


class TestAuthorizationBoundaries:
    async def test_non_member_cannot_read_a_group(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)

        response = await client.get(f"/api/v1/groups/{group['id']}", headers=outsider.headers)

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_MEMBER"

    async def test_non_member_cannot_read_the_roster(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)

        response = await client.get(
            f"/api/v1/groups/{group['id']}/members", headers=outsider.headers
        )
        assert response.status_code == 403

    async def test_plain_member_cannot_edit_the_group(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        response = await client.patch(
            f"/api/v1/groups/{group['id']}", json={"name": "Hijacked"}, headers=sai.headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    async def test_admin_can_edit_the_group(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        promote = await client.patch(
            f"/api/v1/groups/{group['id']}/members/{sai.user_id}",
            json={"role": "admin"},
            headers=ravi.headers,
        )
        assert promote.status_code == 200
        assert promote.json()["role"] == "admin"

        response = await client.patch(
            f"/api/v1/groups/{group['id']}", json={"name": "RENAMED"}, headers=sai.headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "RENAMED"

    async def test_unauthenticated_requests_are_rejected(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)

        response = await client.get(f"/api/v1/groups/{group['id']}")
        assert response.status_code == 401

    async def test_admin_cannot_change_the_owner(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await client.patch(
            f"/api/v1/groups/{group['id']}/members/{sai.user_id}",
            json={"role": "admin"},
            headers=ravi.headers,
        )

        response = await client.patch(
            f"/api/v1/groups/{group['id']}/members/{ravi.user_id}",
            json={"status": "removed"},
            headers=sai.headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "CANNOT_MODIFY_OWNER"

    async def test_ownership_transfer_is_refused(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        response = await client.patch(
            f"/api/v1/groups/{group['id']}/members/{sai.user_id}",
            json={"role": "owner"},
            headers=ravi.headers,
        )
        assert response.status_code == 403


class TestInviteAndJoin:
    async def test_join_with_a_valid_code(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)

        response = await join_group(client, sai, group["join_code"])

        assert response.status_code == 200
        assert response.json()["my_role"] == "member"
        assert response.json()["member_count"] == 2

    async def test_join_code_is_case_and_hyphen_insensitive(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)

        typed = group["join_code"].lower().replace("-", "")
        response = await join_group(client, sai, typed)

        assert response.status_code == 200

    async def test_invalid_code_is_a_clean_404(
        self, client: AsyncClient, register_actor, join_group
    ) -> None:
        sai = await register_actor(client, "Sai")
        response = await join_group(client, sai, "ZZ-ZZZ")
        assert response.status_code == 404
        assert response.json()["code"] == "INVALID_CODE"

    async def test_duplicate_join_conflicts_rather_than_duplicating_membership(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        response = await join_group(client, sai, group["join_code"])

        assert response.status_code == 409
        assert response.json()["code"] == "ALREADY_MEMBER"

        roster = await client.get(
            f"/api/v1/groups/{group['id']}/members", headers=ravi.headers
        )
        assert len(roster.json()) == 2

    async def test_owner_rejoining_own_group_conflicts(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)
        response = await join_group(client, ravi, group["join_code"])
        assert response.status_code == 409

    async def test_join_by_id_requires_the_matching_code(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        arjun = await register_actor(client, "Arjun")
        sai = await register_actor(client, "Sai")
        target = await create_group(client, ravi, name="Target")
        other = await create_group(client, arjun, name="Other")

        # A code that is genuinely valid — for a different group — must not open this one.
        response = await client.post(
            f"/api/v1/groups/{target['id']}/join",
            json={"join_code": other["join_code"]},
            headers=sai.headers,
        )

        assert response.status_code == 404
        assert response.json()["code"] == "INVALID_CODE"

    async def test_join_by_id_with_the_right_code_works(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/join",
            json={"join_code": group["join_code"]},
            headers=sai.headers,
        )
        assert response.status_code == 200

    async def test_a_member_who_left_may_rejoin(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await client.post(f"/api/v1/groups/{group['id']}/leave", headers=sai.headers)

        response = await join_group(client, sai, group["join_code"])

        assert response.status_code == 200
        assert response.json()["member_count"] == 2

    async def test_a_removed_member_may_not_rejoin(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        # An invite code must not be a way around a moderation decision.
        ravi = await register_actor(client, "Ravi")
        kiran = await register_actor(client, "Kiran")
        group = await create_group(client, ravi)
        await join_group(client, kiran, group["join_code"])
        removed = await client.patch(
            f"/api/v1/groups/{group['id']}/members/{kiran.user_id}",
            json={"status": "removed"},
            headers=ravi.headers,
        )
        assert removed.status_code == 200

        response = await join_group(client, kiran, group["join_code"])

        assert response.status_code == 403
        assert response.json()["code"] == "MEMBER_REMOVED"

    async def test_an_admin_can_reinstate_a_removed_member(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        kiran = await register_actor(client, "Kiran")
        group = await create_group(client, ravi)
        await join_group(client, kiran, group["join_code"])
        await client.patch(
            f"/api/v1/groups/{group['id']}/members/{kiran.user_id}",
            json={"status": "removed"},
            headers=ravi.headers,
        )

        response = await client.patch(
            f"/api/v1/groups/{group['id']}/members/{kiran.user_id}",
            json={"status": "active"},
            headers=ravi.headers,
        )

        assert response.status_code == 200
        assert response.json()["status"] == "active"


class TestLeave:
    async def test_member_can_leave(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])

        response = await client.post(
            f"/api/v1/groups/{group['id']}/leave", headers=sai.headers
        )

        assert response.status_code == 204
        after = await client.get(f"/api/v1/groups/{group['id']}", headers=sai.headers)
        assert after.status_code == 403

    async def test_owner_cannot_leave(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        group = await create_group(client, ravi)

        response = await client.post(
            f"/api/v1/groups/{group['id']}/leave", headers=ravi.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "OWNER_CANNOT_LEAVE"

    async def test_leaving_removes_the_group_from_my_list(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await client.post(f"/api/v1/groups/{group['id']}/leave", headers=sai.headers)

        response = await client.get("/api/v1/groups", headers=sai.headers)
        assert response.json() == []


class TestRoster:
    async def test_roster_orders_owner_first(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        meera = await register_actor(client, "Meera")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await join_group(client, meera, group["join_code"])
        await client.patch(
            f"/api/v1/groups/{group['id']}/members/{meera.user_id}",
            json={"role": "admin"},
            headers=ravi.headers,
        )

        response = await client.get(
            f"/api/v1/groups/{group['id']}/members", headers=ravi.headers
        )

        assert [m["display_name"] for m in response.json()] == ["Ravi", "Meera", "Sai"]
        assert [m["role"] for m in response.json()] == ["owner", "admin", "member"]

    async def test_roster_excludes_members_who_left(
        self, client: AsyncClient, register_actor, create_group, join_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await client.post(f"/api/v1/groups/{group['id']}/leave", headers=sai.headers)

        response = await client.get(
            f"/api/v1/groups/{group['id']}/members", headers=ravi.headers
        )
        assert [m["display_name"] for m in response.json()] == ["Ravi"]


class TestActivityFeed:
    async def test_feed_reports_joins_and_challenge_creations(
        self, client: AsyncClient, register_actor, create_group, join_group, create_challenge
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        sai = await register_actor(client, "Sai")
        group = await create_group(client, ravi)
        await join_group(client, sai, group["join_code"])
        await create_challenge(client, ravi, group["id"])

        response = await client.get(
            f"/api/v1/groups/{group['id']}/activity", headers=ravi.headers
        )

        assert response.status_code == 200
        kinds = {entry["kind"] for entry in response.json()}
        assert kinds == {"member_joined", "challenge_created"}

    async def test_feed_is_member_only(
        self, client: AsyncClient, register_actor, create_group
    ) -> None:
        ravi = await register_actor(client, "Ravi")
        outsider = await register_actor(client, "Outsider")
        group = await create_group(client, ravi)

        response = await client.get(
            f"/api/v1/groups/{group['id']}/activity", headers=outsider.headers
        )
        assert response.status_code == 403
