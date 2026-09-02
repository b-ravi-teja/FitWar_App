"""Chat persistence, authorization, reactions, and Redis pub/sub delivery.

Realtime is tested against a real Redis because the guarantee under test is that Postgres
stays authoritative when Redis is not — a mocked broker would assert nothing about that.
"""

import asyncio
import json
import uuid
from contextlib import contextmanager

from sqlalchemy import func, select

from app.core.realtime import group_channel, publish_realtime
from app.core.redis import get_redis
from app.models.media import GroupMessage, MessageReaction


async def _group(client, register_actor, create_group):  # type: ignore[no-untyped-def]
    owner = await register_actor(client, "Owner")
    group = await create_group(client, owner)
    return owner, group


async def _post(client, actor, group_id, text):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/groups/{group_id}/messages", json={"content": text}, headers=actor.headers
    )


class TestChatAuthorization:
    async def test_a_member_can_read_and_post(
        self, client, register_actor, create_group
    ) -> None:
        owner, group = await _group(client, register_actor, create_group)

        posted = await _post(client, owner, group["id"], "First blood")
        history = await client.get(
            f"/api/v1/groups/{group['id']}/messages", headers=owner.headers
        )

        assert posted.status_code == 201
        assert history.json()["items"][0]["content"] == "First blood"

    async def test_a_non_member_is_blocked(
        self, client, register_actor, create_group
    ) -> None:
        _, group = await _group(client, register_actor, create_group)
        outsider = await register_actor(client, "Outsider")

        read = await client.get(
            f"/api/v1/groups/{group['id']}/messages", headers=outsider.headers
        )
        write = await _post(client, outsider, group["id"], "let me in")

        assert read.status_code == 403
        assert write.status_code == 403

    async def test_a_member_who_left_can_no_longer_post(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """Membership is re-checked per request — leaving takes effect immediately."""
        _, group = await _group(client, register_actor, create_group)
        member = await register_actor(client, "Leaver")
        await join_group(client, member, group["join_code"])
        assert (await _post(client, member, group["id"], "still here")).status_code == 201

        await client.post(f"/api/v1/groups/{group['id']}/leave", headers=member.headers)

        after = await _post(client, member, group["id"], "sneaking back")
        assert after.status_code == 403

    async def test_chat_requires_authentication(
        self, client, register_actor, create_group
    ) -> None:
        _, group = await _group(client, register_actor, create_group)
        assert (
            await client.get(f"/api/v1/groups/{group['id']}/messages")
        ).status_code == 401


class TestPersistenceAndPagination:
    async def test_messages_are_durable_in_postgres(
        self, client, register_actor, create_group, db_session
    ) -> None:
        """Postgres is the source of truth; Redis is transport only (§22)."""
        owner, group = await _group(client, register_actor, create_group)

        await _post(client, owner, group["id"], "durable")

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(GroupMessage)
                .where(GroupMessage.group_id == uuid.UUID(group["id"]))
            )
        ).scalar_one()
        assert count == 1

    async def test_history_is_newest_first(
        self, client, register_actor, create_group
    ) -> None:
        owner, group = await _group(client, register_actor, create_group)
        for i in range(3):
            await _post(client, owner, group["id"], f"msg-{i}")

        items = (
            await client.get(
                f"/api/v1/groups/{group['id']}/messages", headers=owner.headers
            )
        ).json()["items"]

        assert [m["content"] for m in items] == ["msg-2", "msg-1", "msg-0"]

    async def test_pagination_walks_the_whole_history_without_repeats(
        self, client, register_actor, create_group
    ) -> None:
        """Keyset paging, so a growing history doesn't degrade into an offset scan."""
        owner, group = await _group(client, register_actor, create_group)
        for i in range(7):
            await _post(client, owner, group["id"], f"m{i}")

        seen: list[str] = []
        cursor = None
        for _ in range(5):
            url = f"/api/v1/groups/{group['id']}/messages?limit=3"
            if cursor:
                url += f"&before={cursor[0]}&before_id={cursor[1]}"
            page = (await client.get(url, headers=owner.headers)).json()
            seen.extend(m["content"] for m in page["items"])
            cursor = (
                (page["next_cursor"], page["next_cursor_id"])
                if page["next_cursor"]
                else None
            )
            if not cursor:
                break

        assert len(seen) == len(set(seen)) == 7

    async def test_limit_is_capped(self, client, register_actor, create_group) -> None:
        owner, group = await _group(client, register_actor, create_group)
        response = await client.get(
            f"/api/v1/groups/{group['id']}/messages?limit=5000", headers=owner.headers
        )
        assert response.status_code == 422


class TestReactions:
    async def _message(self, client, actor, group_id):  # type: ignore[no-untyped-def]
        return (await _post(client, actor, group_id, "react to me")).json()["id"]

    async def test_adding_a_reaction_is_idempotent(
        self, client, register_actor, create_group, db_session
    ) -> None:
        owner, group = await _group(client, register_actor, create_group)
        message_id = await self._message(client, owner, group["id"])

        for _ in range(4):
            response = await client.post(
                f"/api/v1/groups/{group['id']}/messages/{message_id}/reactions",
                json={"emoji": "🔥", "add": True},
                headers=owner.headers,
            )
            assert response.status_code == 204

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(MessageReaction)
                .where(MessageReaction.message_id == uuid.UUID(message_id))
            )
        ).scalar_one()
        assert count == 1

    async def test_removing_is_idempotent_too(
        self, client, register_actor, create_group
    ) -> None:
        owner, group = await _group(client, register_actor, create_group)
        message_id = await self._message(client, owner, group["id"])
        await client.post(
            f"/api/v1/groups/{group['id']}/messages/{message_id}/reactions",
            json={"emoji": "🔥", "add": True},
            headers=owner.headers,
        )

        for _ in range(3):
            await client.post(
                f"/api/v1/groups/{group['id']}/messages/{message_id}/reactions",
                json={"emoji": "🔥", "add": False},
                headers=owner.headers,
            )

        items = (
            await client.get(
                f"/api/v1/groups/{group['id']}/messages", headers=owner.headers
            )
        ).json()["items"]
        assert items[0]["reactions"] == []

    async def test_summary_counts_and_flags_the_caller(
        self, client, register_actor, create_group, join_group
    ) -> None:
        owner, group = await _group(client, register_actor, create_group)
        friend = await register_actor(client, "Friend")
        await join_group(client, friend, group["join_code"])
        message_id = await self._message(client, owner, group["id"])
        for actor in (owner, friend):
            await client.post(
                f"/api/v1/groups/{group['id']}/messages/{message_id}/reactions",
                json={"emoji": "💪", "add": True},
                headers=actor.headers,
            )

        items = (
            await client.get(
                f"/api/v1/groups/{group['id']}/messages", headers=friend.headers
            )
        ).json()["items"]

        reaction = items[0]["reactions"][0]
        assert reaction == {"emoji": "💪", "count": 2, "reacted_by_me": True}

    async def test_an_unlisted_emoji_is_refused(
        self, client, register_actor, create_group
    ) -> None:
        """V1 ships a fixed set, not an open field (§18)."""
        owner, group = await _group(client, register_actor, create_group)
        message_id = await self._message(client, owner, group["id"])

        response = await client.post(
            f"/api/v1/groups/{group['id']}/messages/{message_id}/reactions",
            json={"emoji": "🚀", "add": True},
            headers=owner.headers,
        )

        assert response.status_code == 400
        assert response.json()["code"] == "REACTION_NOT_ALLOWED"

    async def test_cannot_react_across_groups(
        self, client, register_actor, create_group
    ) -> None:
        """A message id from another group must not resolve — same 404 as a missing one."""
        owner_a, group_a = await _group(client, register_actor, create_group)
        owner_b = await register_actor(client, "OtherOwner")
        group_b = await create_group(client, owner_b, name="OTHER SQUAD")
        message_id = await self._message(client, owner_a, group_a["id"])

        response = await client.post(
            f"/api/v1/groups/{group_b['id']}/messages/{message_id}/reactions",
            json={"emoji": "🔥", "add": True},
            headers=owner_b.headers,
        )

        assert response.status_code == 404


class TestRealtimeTransport:
    async def test_a_posted_message_is_published_to_the_group_channel(
        self, client, register_actor, create_group
    ) -> None:
        """Redis carries it; Postgres already holds it."""
        owner, group = await _group(client, register_actor, create_group)
        channel = group_channel(uuid.UUID(group["id"]))
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(channel)
        await asyncio.sleep(0.1)

        await _post(client, owner, group["id"], "live one")

        received = None
        for _ in range(40):
            event = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if event:
                received = json.loads(event["data"])
                break
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

        assert received is not None, "expected the message on the group channel"
        assert received["type"] == "chat_message"
        assert received["content"] == "live one"

    async def test_publishing_to_a_broken_redis_does_not_raise(self) -> None:
        """Realtime is additive: a broker failure must never break a durable write."""
        from redis.asyncio import Redis

        import app.core.realtime as realtime

        broken = Redis.from_url("redis://127.0.0.1:6399/0")
        original = realtime.get_redis
        realtime.get_redis = lambda: broken  # type: ignore[assignment]
        try:
            delivered = await publish_realtime("rt:v1:group:x", {"type": "noop"})
        finally:
            realtime.get_redis = original  # type: ignore[assignment]

        assert delivered is False

    async def test_chat_still_works_when_realtime_publishing_fails(
        self, client, register_actor, create_group, db_session
    ) -> None:
        """The REST fallback guarantee (§20, §22), proven end to end."""
        from redis.asyncio import Redis

        import app.core.realtime as realtime

        owner, group = await _group(client, register_actor, create_group)
        broken = Redis.from_url("redis://127.0.0.1:6399/0")
        original = realtime.get_redis
        realtime.get_redis = lambda: broken  # type: ignore[assignment]
        try:
            posted = await _post(client, owner, group["id"], "survives redis outage")
        finally:
            realtime.get_redis = original  # type: ignore[assignment]

        assert posted.status_code == 201
        history = await client.get(
            f"/api/v1/groups/{group['id']}/messages", headers=owner.headers
        )
        assert history.json()["items"][0]["content"] == "survives redis outage"

    async def test_a_reconnecting_client_recovers_missed_messages_over_rest(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """Delivery is not exactly-once; REST is how a client converges (§23)."""
        owner, group = await _group(client, register_actor, create_group)
        watcher = await register_actor(client, "Watcher")
        await join_group(client, watcher, group["join_code"])

        first = (
            await client.get(
                f"/api/v1/groups/{group['id']}/messages", headers=watcher.headers
            )
        ).json()
        # ... watcher's socket is down here ...
        await _post(client, owner, group["id"], "missed while offline")

        after_reconnect = (
            await client.get(
                f"/api/v1/groups/{group['id']}/messages", headers=watcher.headers
            )
        ).json()

        assert len(first["items"]) == 0
        assert after_reconnect["items"][0]["content"] == "missed while offline"


class TestWebSocketAuthorization:
    """A valid JWT is not enough — membership of the specific resource is checked too.

    These use Starlette's `TestClient`, which drives the app on its own event loop. The
    process-wide Redis client is cached per loop, so it is reset around each socket:
    otherwise the app's shutdown would try to close a connection created on pytest's
    loop, which asyncio refuses.
    """

    @contextmanager
    def _socket_client(self):  # type: ignore[no-untyped-def]
        from starlette.testclient import TestClient

        from app.core.redis import get_redis
        from app.main import create_app

        get_redis.cache_clear()
        try:
            with TestClient(create_app()) as http:
                yield http
        finally:
            get_redis.cache_clear()

    def _expect_refused(self, http, url: str) -> int:  # type: ignore[no-untyped-def]
        from starlette.websockets import WebSocketDisconnect

        try:
            with http.websocket_connect(url):
                raise AssertionError(f"socket should have been refused: {url}")
        except WebSocketDisconnect as exc:
            return int(exc.code)

    async def test_a_socket_without_a_token_is_refused(
        self, client, register_actor, create_group
    ) -> None:
        _, group = await _group(client, register_actor, create_group)

        with self._socket_client() as http:
            code = self._expect_refused(http, f"/api/v1/ws/groups/{group['id']}")

        assert code == 4403

    async def test_a_non_member_cannot_subscribe(
        self, client, register_actor, create_group
    ) -> None:
        """Authenticated but unauthorized — the JWT alone buys nothing (§21)."""
        from app.core.security import create_access_token

        _, group = await _group(client, register_actor, create_group)
        outsider = await register_actor(client, "Outsider")
        token = create_access_token(subject=str(outsider.user_id))

        with self._socket_client() as http:
            code = self._expect_refused(
                http, f"/api/v1/ws/groups/{group['id']}?token={token}"
            )

        assert code == 4403

    async def test_an_unknown_group_is_refused_identically(
        self, client, register_actor
    ) -> None:
        """Same close code as a forbidden group, so an outsider cannot tell whether a
        private group exists (§21)."""
        from app.core.security import create_access_token

        actor = await register_actor(client, "Prober")
        token = create_access_token(subject=str(actor.user_id))

        with self._socket_client() as http:
            code = self._expect_refused(
                http, f"/api/v1/ws/groups/{uuid.uuid4()}?token={token}"
            )

        assert code == 4403
