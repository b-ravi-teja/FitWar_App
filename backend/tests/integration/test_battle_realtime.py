"""Battle realtime: what is published, who may subscribe, and what happens without it.

Realtime is additive (§14). Every assertion below about delivery is paired with one
about REST still being complete and authoritative on its own, because that — not the
socket — is what the product actually depends on.
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.realtime import battle_channel, group_channel
from app.core.redis import get_redis


async def _squad(client, register_actor, create_group, join_group, size: int = 2):  # type: ignore[no-untyped-def]
    actors = [await register_actor(client, f"Live{index}") for index in range(size)]
    group = await create_group(client, actors[0])
    for actor in actors[1:]:
        assert (await join_group(client, actor, group["join_code"])).status_code == 200
    return actors, group


async def _create_battle(client, actor, opponent, group, **overrides) -> Any:  # type: ignore[no-untyped-def]
    payload: dict[str, Any] = {
        "opponent_user_id": str(opponent.user_id),
        "activity_type": "steps",
        "target_value": "10000",
        "duration_days": 1,
        "group_id": group["id"],
    }
    payload.update(overrides)
    return await client.post("/api/v1/battles", json=payload, headers=actor.headers)


async def _verify(client, actor, battle_id, value="12000") -> Any:  # type: ignore[no-untyped-def]
    battle = (await client.get(f"/api/v1/battles/{battle_id}", headers=actor.headers)).json()
    return await client.post(
        f"/api/v1/battles/{battle_id}/verify",
        json={
            "provider": "apple_health",
            "evidence": {
                "metric": "steps",
                "value": value,
                "unit": "steps",
                "period_start": battle["start_at"],
                "period_end": datetime.now(UTC).isoformat(),
                "was_user_entered": False,
            },
        },
        headers=actor.headers,
    )


async def _drain(pubsub, limit: int = 40) -> list[dict[str, Any]]:
    events = []
    for _ in range(limit):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if message:
            events.append(json.loads(message["data"]))
    return events


class TestPublishedEvents:
    async def test_an_invitation_reaches_the_squad_channel(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """The opponent doesn't know the battle id yet, so discovery rides the group
        channel they are already on. Everything after that is battle-scoped."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(group_channel(uuid.UUID(group["id"])))
        await asyncio.sleep(0.1)

        await _create_battle(client, alpha, bravo, group)
        events = await _drain(pubsub)

        await pubsub.unsubscribe()
        await pubsub.aclose()
        assert any(event["type"] == "battle_invited" for event in events)

    async def test_acceptance_progress_and_completion_all_reach_the_battle_channel(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(battle_channel(uuid.UUID(battle["id"])))
        await asyncio.sleep(0.1)

        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], "12000")
        await _verify(client, bravo, battle["id"], "11000")
        events = await _drain(pubsub, limit=80)

        await pubsub.unsubscribe()
        await pubsub.aclose()
        types = [event["type"] for event in events]
        assert "battle_status_changed" in types
        assert "battle_progress" in types
        assert "battle_completed" in types

    async def test_events_carry_no_scores_or_evidence(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """§18: the socket is a nudge to re-read REST, never a data channel. A payload
        with numbers in it would be a way around the read authorization."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(battle_channel(uuid.UUID(battle["id"])))
        await asyncio.sleep(0.1)

        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], "12000")
        events = await _drain(pubsub, limit=80)

        await pubsub.unsubscribe()
        await pubsub.aclose()
        assert events
        allowed = {"type", "battle_id", "group_id", "status", "winner_user_id", "opponent_user_id"}
        for event in events:
            assert set(event) <= allowed, event

    async def test_the_completion_event_names_the_winner_only_after_the_fact(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(battle_channel(uuid.UUID(battle["id"])))
        await asyncio.sleep(0.1)

        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], "12000")
        await _verify(client, bravo, battle["id"], "11000")
        events = await _drain(pubsub, limit=80)

        await pubsub.unsubscribe()
        await pubsub.aclose()
        completed = [event for event in events if event["type"] == "battle_completed"]
        assert completed and completed[0]["winner_user_id"] == str(alpha.user_id)
        progress = [event for event in events if event["type"] == "battle_progress"]
        assert all("winner_user_id" not in event for event in progress)


class TestRestFallback:
    async def test_a_battle_plays_through_with_realtime_completely_broken(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """The whole lifecycle with Redis pointed at a dead port. REST is the product;
        the socket is a convenience (§14)."""
        from redis.asyncio import Redis

        import app.core.realtime as realtime

        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        broken = Redis.from_url("redis://127.0.0.1:6399/0")
        original = realtime.get_redis
        realtime.get_redis = lambda: broken  # type: ignore[assignment]
        try:
            battle = (await _create_battle(client, alpha, bravo, group)).json()
            accepted = await client.post(
                f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers
            )
            await _verify(client, alpha, battle["id"], "12000")
            final = (await _verify(client, bravo, battle["id"], "11000")).json()["battle"]
        finally:
            realtime.get_redis = original  # type: ignore[assignment]

        assert accepted.status_code == 200
        assert final["status"] == "completed"
        assert final["winner_user_id"] == str(alpha.user_id)

    async def test_rest_alone_reports_the_full_state_a_socket_would_have_streamed(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """What a client that missed every event recovers on reconnect."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], "12000")
        await _verify(client, bravo, battle["id"], "11000")

        body = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=bravo.headers)
        ).json()

        assert body["status"] == "completed"
        assert body["my_outcome"] == "lost"
        assert body["winner_user_id"] == str(alpha.user_id)
        assert Decimal(body["sides"][0]["score"]) > 0


class TestSocketAuthorization:
    """Resource authorization on the socket itself, not merely a valid token (§15).

    These use `live_client` for setup and Starlette's `TestClient` for the socket. The
    setup has to be committed: the socket gateway opens its own session, so rows that
    only exist inside a rolled-back test transaction are invisible to it — and a
    "forbidden" assertion would then pass because the *user* didn't exist, proving
    nothing about the authorization rule. Committing is also what lets the admitted
    case be tested at all.
    """

    @asynccontextmanager
    async def _socket_client(self):  # type: ignore[no-untyped-def]
        """A `TestClient` that can safely reach Postgres and Redis.

        `TestClient` drives the app on its own event loop, and both the SQLAlchemy
        connection pool and the process-wide Redis client hold objects bound to the loop
        that created them. Handing either across loops raises "attached to a different
        loop", so both are cleared on the way in and on the way out — the pool refills
        with connections belonging to whichever loop asks next.
        """
        from starlette.testclient import TestClient

        from app.core.database import _engine
        from app.core.redis import get_redis as cached_redis
        from app.main import create_app

        await _engine.dispose()
        cached_redis.cache_clear()
        try:
            with TestClient(create_app()) as http:
                yield http
        finally:
            cached_redis.cache_clear()
            await _engine.dispose()

    def _expect_refused(self, http, url: str) -> int:  # type: ignore[no-untyped-def]
        from starlette.websockets import WebSocketDisconnect

        try:
            with http.websocket_connect(url):
                raise AssertionError(f"socket should have been refused: {url}")
        except WebSocketDisconnect as exc:
            return int(exc.code)

    async def _committed_battle(self, live_client, extra: int = 0):  # type: ignore[no-untyped-def]
        actors = []
        for index in range(2 + extra):
            email = f"sock{index}-{uuid.uuid4().hex[:10]}@example.com"
            body = (
                await live_client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": email,
                        "password": "hunter2222",
                        "display_name": f"Sock{index}",
                    },
                )
            ).json()
            user_id = uuid.UUID(body["user_id"])
            live_client.created_users.append(user_id)
            actors.append((user_id, {"Authorization": f"Bearer {body['access_token']}"}))

        group = (
            await live_client.post(
                "/api/v1/groups",
                json={"name": "SOCKET SQUAD", "timezone": "Asia/Kolkata"},
                headers=actors[0][1],
            )
        ).json()
        for _, headers in actors[1:]:
            assert (
                await live_client.post(
                    "/api/v1/groups/join",
                    json={"join_code": group["join_code"]},
                    headers=headers,
                )
            ).status_code == 200

        battle = (
            await live_client.post(
                "/api/v1/battles",
                json={
                    "opponent_user_id": str(actors[1][0]),
                    "activity_type": "steps",
                    "target_value": "10000",
                    "duration_days": 1,
                    "group_id": group["id"],
                },
                headers=actors[0][1],
            )
        ).json()
        return actors, group, battle

    async def test_a_battle_socket_without_a_token_is_refused(self, live_client) -> None:  # type: ignore[no-untyped-def]
        _, _, battle = await self._committed_battle(live_client)

        async with self._socket_client() as http:
            code = self._expect_refused(http, f"/api/v1/ws/battles/{battle['id']}")

        assert code == 4403

    async def test_a_participant_is_admitted(self, live_client) -> None:  # type: ignore[no-untyped-def]
        from app.core.security import create_access_token

        actors, _, battle = await self._committed_battle(live_client)
        token = create_access_token(subject=str(actors[1][0]))

        async with self._socket_client() as http:
            with http.websocket_connect(
                f"/api/v1/ws/battles/{battle['id']}?token={token}"
            ) as socket:
                assert socket is not None

    async def test_a_squad_mate_who_is_not_playing_cannot_subscribe(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Group membership is deliberately not enough — a 1v1 is private to its two."""
        from app.core.security import create_access_token

        actors, _, battle = await self._committed_battle(live_client, extra=1)
        bystander = create_access_token(subject=str(actors[2][0]))

        async with self._socket_client() as http:
            code = self._expect_refused(
                http, f"/api/v1/ws/battles/{battle['id']}?token={bystander}"
            )

        assert code == 4403

    async def test_an_unknown_battle_is_refused_exactly_like_a_forbidden_one(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Same close code either way, so a socket cannot probe for battle ids."""
        from app.core.security import create_access_token

        actors, _, battle = await self._committed_battle(live_client, extra=1)
        bystander = create_access_token(subject=str(actors[2][0]))

        async with self._socket_client() as http:
            forbidden = self._expect_refused(
                http, f"/api/v1/ws/battles/{battle['id']}?token={bystander}"
            )
            unknown = self._expect_refused(
                http, f"/api/v1/ws/battles/{uuid.uuid4()}?token={bystander}"
            )

        assert forbidden == unknown == 4403

    async def test_a_completed_battle_stays_private_to_its_two_players(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Authorization does not relax once the battle is over."""
        from app.core.security import create_access_token

        actors, _, battle = await self._committed_battle(live_client, extra=1)
        await live_client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=actors[1][1]
        )
        for (_, headers), value in zip(actors[:2], ("12000", "11000"), strict=True):
            window = (
                await live_client.get(
                    f"/api/v1/battles/{battle['id']}", headers=headers
                )
            ).json()
            await live_client.post(
                f"/api/v1/battles/{battle['id']}/verify",
                json={
                    "provider": "apple_health",
                    "evidence": {
                        "metric": "steps",
                        "value": value,
                        "unit": "steps",
                        "period_start": window["start_at"],
                        "period_end": datetime.now(UTC).isoformat(),
                        "was_user_entered": False,
                    },
                },
                headers=headers,
            )
        bystander = create_access_token(subject=str(actors[2][0]))

        async with self._socket_client() as http:
            code = self._expect_refused(
                http, f"/api/v1/ws/battles/{battle['id']}?token={bystander}"
            )

        assert code == 4403

    async def test_a_disconnected_client_recovers_everything_over_rest(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Reconnect is a REST read, by design: delivery is not exactly-once, so the
        socket is never the record of what happened while it was gone (§14)."""
        from app.core.security import create_access_token

        actors, _, battle = await self._committed_battle(live_client)
        token = create_access_token(subject=str(actors[1][0]))

        # Connect, then drop before anything happens.
        async with self._socket_client() as http:
            with http.websocket_connect(f"/api/v1/ws/battles/{battle['id']}?token={token}"):
                pass

        # The whole battle plays out while that client is away.
        await live_client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=actors[1][1]
        )
        for (_, headers), value in zip(actors, ("12000", "11000"), strict=True):
            window = (
                await live_client.get(
                    f"/api/v1/battles/{battle['id']}", headers=headers
                )
            ).json()
            await live_client.post(
                f"/api/v1/battles/{battle['id']}/verify",
                json={
                    "provider": "apple_health",
                    "evidence": {
                        "metric": "steps",
                        "value": value,
                        "unit": "steps",
                        "period_start": window["start_at"],
                        "period_end": datetime.now(UTC).isoformat(),
                        "was_user_entered": False,
                    },
                },
                headers=headers,
            )

        # Reconnecting and re-reading recovers the full outcome.
        async with self._socket_client() as http:
            with http.websocket_connect(f"/api/v1/ws/battles/{battle['id']}?token={token}"):
                pass
        recovered = (
            await live_client.get(f"/api/v1/battles/{battle['id']}", headers=actors[1][1])
        ).json()

        assert recovered["status"] == "completed"
        assert recovered["winner_user_id"] == str(actors[0][0])
        assert recovered["my_outcome"] == "lost"
