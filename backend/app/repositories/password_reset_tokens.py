import hashlib
import uuid

from redis.asyncio import Redis

_KEY_PREFIX = "fitwar:password_reset:"
_TTL_SECONDS = 30 * 60  # ADR 0007: short-lived, single-use


class PasswordResetTokenRepository:
    """Redis-backed, not Postgres — deliberately (ADR 0007): reset tokens are
    ephemeral and single-use, unlike `RefreshToken` which needs durable revocation
    history. TTL handles expiry for free; `consume()` deletes on read for single-use.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _hash(raw_token: str) -> str:
        # Same reasoning as refresh-token hashing (core/security.py): the input is a
        # high-entropy random token, not a low-entropy secret, so a fast deterministic
        # digest is correct and necessary for the lookup — not Argon2.
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    async def store(self, *, raw_token: str, user_id: uuid.UUID) -> None:
        key = _KEY_PREFIX + self._hash(raw_token)
        await self._redis.set(key, str(user_id), ex=_TTL_SECONDS)

    async def consume(self, raw_token: str) -> uuid.UUID | None:
        """Looks up and deletes in one step — a token is valid for exactly one use."""
        key = _KEY_PREFIX + self._hash(raw_token)
        value = await self._redis.getdel(key)
        if value is None:
            return None
        # The client is always constructed with decode_responses=True (core/redis.py),
        # so this is a str at runtime — the stub's wider `bytes | str` union is just
        # imprecise about that, not something to silently ignore either way.
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return uuid.UUID(value)
