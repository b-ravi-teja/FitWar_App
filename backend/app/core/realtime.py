"""Realtime transport: Redis pub/sub behind the WebSocket gateway (Architecture §10).

Redis is **transport only** and never a store (§22). Callers persist to Postgres first
and publish afterwards, so losing Redis costs live delivery and nothing durable.

Publishing is deliberately failure-tolerant: a broken cache must not turn a successful
chat post or a committed game result into a 500.
"""

import json
import uuid
from typing import Any

from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

CHANNEL_PREFIX = "rt:v1"


def group_channel(group_id: uuid.UUID) -> str:
    return f"{CHANNEL_PREFIX}:group:{group_id}"


def challenge_channel(challenge_id: uuid.UUID) -> str:
    return f"{CHANNEL_PREFIX}:challenge:{challenge_id}"


async def publish_realtime(channel: str, payload: dict[str, Any]) -> bool:
    """Fan out one event. Returns whether it actually reached Redis.

    Never raises: REST remains authoritative, and a client that misses this will see the
    same state on its next fetch (§20, §23 — delivery is not exactly-once and clients
    reconcile over REST on reconnect).
    """
    try:
        await get_redis().publish(channel, json.dumps(payload))
        return True
    except RedisError as exc:
        logger.warning("realtime_publish_failed", channel=channel, error=str(exc))
        return False
