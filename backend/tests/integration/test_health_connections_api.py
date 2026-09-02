"""/me/health-connections — connect, list, revoke, and their authorization boundary."""

from datetime import UTC, datetime


class TestConnect:
    async def test_connecting_records_the_link(self, client, register_actor) -> None:  # type: ignore[no-untyped-def]
        actor = await register_actor(client, "Connector")

        response = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=actor.headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["provider"] == "apple_health"
        assert body["status"] == "connected"
        # Nothing has been submitted yet, so the server has observed no sync.
        assert body["last_synced_at"] is None

    async def test_reconnecting_revives_rather_than_duplicating(
        self, client, register_actor
    ) -> None:  # type: ignore[no-untyped-def]
        """Re-granting permission in iOS Settings must not fail or create a second row."""
        actor = await register_actor(client, "Reconnector")
        first = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=actor.headers,
        )
        connection_id = first.json()["id"]
        await client.delete(
            f"/api/v1/me/health-connections/{connection_id}", headers=actor.headers
        )

        second = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=actor.headers,
        )

        assert second.status_code == 201
        assert second.json()["id"] == connection_id
        assert second.json()["status"] == "connected"

    async def test_rejects_an_unknown_provider(self, client, register_actor) -> None:  # type: ignore[no-untyped-def]
        actor = await register_actor(client, "Bogus")

        response = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "fitbit"},
            headers=actor.headers,
        )

        assert response.status_code == 422


class TestListAndRevoke:
    async def test_lists_only_the_callers_connections(
        self, client, register_actor
    ) -> None:  # type: ignore[no-untyped-def]
        mine = await register_actor(client, "Mine")
        theirs = await register_actor(client, "Theirs")
        await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=theirs.headers,
        )

        response = await client.get("/api/v1/me/health-connections", headers=mine.headers)

        assert response.status_code == 200
        assert response.json() == []

    async def test_revoking_marks_the_connection_revoked(
        self, client, register_actor
    ) -> None:  # type: ignore[no-untyped-def]
        actor = await register_actor(client, "Revoker")
        created = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=actor.headers,
        )
        connection_id = created.json()["id"]

        response = await client.delete(
            f"/api/v1/me/health-connections/{connection_id}", headers=actor.headers
        )

        assert response.status_code == 204
        listed = await client.get("/api/v1/me/health-connections", headers=actor.headers)
        assert listed.json()[0]["status"] == "revoked"

    async def test_cannot_revoke_someone_elses_connection(
        self, client, register_actor
    ) -> None:  # type: ignore[no-untyped-def]
        """A connection id from another account must not resolve — holding an id is
        not authorization, and the error must not confirm the id exists."""
        owner = await register_actor(client, "Owner")
        attacker = await register_actor(client, "Attacker")
        created = await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=owner.headers,
        )
        connection_id = created.json()["id"]

        response = await client.delete(
            f"/api/v1/me/health-connections/{connection_id}", headers=attacker.headers
        )

        assert response.status_code == 404
        # The owner's connection is untouched.
        listed = await client.get("/api/v1/me/health-connections", headers=owner.headers)
        assert listed.json()[0]["status"] == "connected"

    async def test_requires_authentication(self, client) -> None:  # type: ignore[no-untyped-def]
        assert (await client.get("/api/v1/me/health-connections")).status_code == 401


class TestSyncObservation:
    async def test_successful_verification_records_a_sync(
        self, client, register_actor, create_group, create_challenge
    ) -> None:  # type: ignore[no-untyped-def]
        """`last_synced_at` is the server's own observation that evidence arrived —
        the one health signal that isn't a client claim."""
        actor = await register_actor(client, "Syncer")
        await client.post(
            "/api/v1/me/health-connections",
            json={"provider": "apple_health"},
            headers=actor.headers,
        )
        group = await create_group(client, actor)
        challenge = (await create_challenge(client, actor, group["id"])).json()
        day = (
            await client.get(
                f"/api/v1/challenges/{challenge['id']}/progress/today", headers=actor.headers
            )
        ).json()

        await client.post(
            f"/api/v1/challenges/{challenge['id']}/verify",
            json={
                "provider": "apple_health",
                "evidence": {
                    "metric": "steps",
                    "value": "12000",
                    "unit": "steps",
                    "period_start": day["window_start_at"],
                    "period_end": datetime.now(UTC).isoformat(),
                },
            },
            headers=actor.headers,
        )

        listed = await client.get("/api/v1/me/health-connections", headers=actor.headers)
        assert listed.json()[0]["last_synced_at"] is not None
