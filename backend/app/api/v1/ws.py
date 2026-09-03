"""WebSocket gateway (Architecture §10, §21).

Realtime is additive: everything delivered here is also readable over REST, and a client
that never connects still works (§20). Delivery is not exactly-once — clients reconcile
against REST on reconnect (§23).

Authorization is per-resource, not merely per-token: a valid JWT proves who you are, and
membership of *this* group is checked separately before any subscription is accepted.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError

from app.core.database import _session_factory as session_factory
from app.core.logging import get_logger
from app.core.realtime import battle_channel, group_channel
from app.core.redis import get_redis
from app.core.security import InvalidTokenError, decode_access_token
from app.models.user import UserStatus
from app.repositories.battles import BattleRepository
from app.repositories.groups import GroupMemberRepository
from app.repositories.users import UserRepository

logger = get_logger(__name__)

router = APIRouter(tags=["realtime"])

# Close codes. 4401/4403 mirror HTTP semantics in the private-use range.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


async def _authorize(token: str | None, group_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve the caller and confirm they may subscribe to this group.

    Returns the user id, or None if either check fails. The *same* None covers "bad
    token", "unknown group" and "not a member", so an unauthorized caller cannot learn
    whether a private group exists (§21).
    """
    if not token:
        return None
    try:
        subject = decode_access_token(token)
        user_id = uuid.UUID(subject)
    except (InvalidTokenError, ValueError):
        return None

    async with session_factory() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        member = await GroupMemberRepository(session).get_active(group_id, user_id)
        if member is None:
            return None
    return user_id


async def _authorize_battle(token: str | None, battle_id: uuid.UUID) -> uuid.UUID | None:
    """Same shape as `_authorize`, against `battle_participant` instead of membership.

    A 1v1 is private to its two players — not to its squad — so squad membership is
    deliberately *not* sufficient here (§15). As above, one `None` covers bad token,
    unknown battle and non-participant, so a socket cannot be used to discover that a
    battle exists.
    """
    if not token:
        return None
    try:
        subject = decode_access_token(token)
        user_id = uuid.UUID(subject)
    except (InvalidTokenError, ValueError):
        return None

    async with session_factory() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return None
        participant = await BattleRepository(session).participant_for(battle_id, user_id)
        if participant is None:
            return None
    return user_id


async def _serve(websocket: WebSocket, channel: str) -> None:
    """Accept the socket and relay one Redis channel onto it until it drops.

    Shared by both gateways so group and battle sockets cannot drift apart in how they
    subscribe, pump, or tear down. Authorization happens *before* this is called — this
    function assumes the caller is already allowed on the channel.
    """
    await websocket.accept()

    try:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(channel)
    except RedisError as exc:
        # Redis is down. The socket closes and the client falls back to REST, which
        # still serves the authoritative state (§22).
        logger.warning("realtime_subscribe_failed", error=str(exc))
        await websocket.close(code=1013)  # try again later
        return

    async def pump() -> None:
        async for event in pubsub.listen():
            if event.get("type") != "message":
                continue
            data = event.get("data")
            try:
                await websocket.send_text(
                    data if isinstance(data, str) else json.dumps(data)
                )
            except Exception:  # client vanished mid-send
                return

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            # Inbound frames are ignored: this socket is delivery-only. Posting goes
            # through REST so one authorization path covers every write.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
        except Exception:  # teardown must not raise
            pass


@router.websocket("/ws/groups/{group_id}")
async def group_socket(
    websocket: WebSocket,
    group_id: uuid.UUID,
    token: str | None = Query(default=None),
) -> None:
    """Subscribe to one group's live events.

    The token arrives as a query parameter because browsers and URLSession cannot set
    headers on a WebSocket handshake. It is an access token — short-lived by design —
    and the connection is authorized before it is accepted, so nothing is delivered to
    an unauthenticated socket.
    """
    user_id = await _authorize(token, group_id)
    if user_id is None:
        # Closed before accept: no channel is ever joined, and the close code is
        # identical whether the group is missing or merely forbidden.
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    await _serve(websocket, group_channel(group_id))


@router.websocket("/ws/battles/{battle_id}")
async def battle_socket(
    websocket: WebSocket,
    battle_id: uuid.UUID,
    token: str | None = Query(default=None),
) -> None:
    """Subscribe to one battle's live events — `battle_status_changed`,
    `battle_progress`, `battle_completed`.

    Only the two participants are admitted, so participant A's socket carries battle A
    and nothing else; there is no channel a third party can reach, before, during or
    after the battle. Events carry ids and a status, never scores or evidence — a
    client re-reads REST for the numbers (§18).
    """
    user_id = await _authorize_battle(token, battle_id)
    if user_id is None:
        await websocket.close(code=CLOSE_FORBIDDEN)
        return
    await _serve(websocket, battle_channel(battle_id))
