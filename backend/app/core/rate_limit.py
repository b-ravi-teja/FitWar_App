"""Redis-backed sliding-window rate limiting (Architecture §7).

Infrastructure, not business logic: this module knows about Redis and HTTP requests
but nothing about auth, challenges, or any other feature. Endpoints opt in
declaratively via `RateLimitGuard` in their route `dependencies=[...]`, so no route
handler contains rate-limit code and no service is coupled to Redis.

Algorithm — sliding window log, not a fixed-window counter. Each accepted request is
one member of a Redis sorted set scored by its millisecond timestamp; the window is
enforced by dropping members older than `now - window` before counting. A fixed-window
counter would let a caller spend a full quota at the end of one window and another at
the start of the next — double the intended rate across the boundary. The whole
check-and-record is a single Lua script, so it is atomic: concurrent requests cannot
interleave between the count and the insert and slip past the limit together.

Rejected requests are deliberately NOT recorded. A blocked caller who keeps hammering
would otherwise keep pushing their own window forward and stay locked out indefinitely.
"""

import enum
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.requests import Request

from app.core.config import RateLimitSettings, Settings, get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.common.exceptions import RateLimitedError
from app.schemas.common import ProblemDetail

logger = get_logger(__name__)

KEY_PREFIX = "rl:v1"

# KEYS[1] = bucket key
# ARGV    = now_ms, window_ms, limit, member
#
# Returns {allowed, remaining, retry_after_ms}. PEXPIRE on every path keeps idle
# buckets from accumulating: a key always dies within one window of its last touch.
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)

if used < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return {1, limit - used - 1, 0}
end

-- Denied. The window frees up when its oldest surviving entry ages out.
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = 0
if oldest[2] then
  retry = (tonumber(oldest[2]) + window) - now
  if retry < 0 then retry = 0 end
end
redis.call('PEXPIRE', key, window)
return {0, 0, retry}
"""


class FailurePolicy(enum.StrEnum):
    """What to do when Redis cannot answer.

    FAIL_CLOSED refuses the request. Used for authentication: an attacker who can
    degrade Redis must not thereby switch off brute-force protection.
    FAIL_OPEN allows it, for endpoints where availability matters more than throttling.
    """

    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"


class IdentitySource(enum.StrEnum):
    """Which caller attribute a bucket counts against."""

    IP = "ip"
    ACCOUNT_EMAIL = "account_email"


class RuleName(enum.StrEnum):
    AUTH_LOGIN_IP = "auth_login_ip"
    AUTH_LOGIN_ACCOUNT = "auth_login_account"
    AUTH_REGISTER_IP = "auth_register_ip"
    AUTH_REFRESH_IP = "auth_refresh_ip"
    AUTH_PASSWORD_RESET_IP = "auth_password_reset_ip"
    AUTH_PASSWORD_RESET_ACCOUNT = "auth_password_reset_account"


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int
    policy: FailurePolicy = FailurePolicy.FAIL_CLOSED


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """The limiter itself. Takes a Redis client, so tests can point it anywhere."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_SLIDING_WINDOW_LUA)

    async def check(self, *, key: str, rule: RateLimitRule) -> RateLimitDecision:
        """Consume one slot. Raises `RedisError` if Redis is unreachable — callers
        decide what that means via `FailurePolicy`, since only they know the endpoint."""
        now_ms = int(time.time() * 1000)
        window_ms = rule.window_seconds * 1000
        raw = await self._script(
            keys=[key],
            args=[now_ms, window_ms, rule.limit, uuid.uuid4().hex],
        )
        allowed, remaining, retry_ms = (int(raw[0]), int(raw[1]), int(raw[2]))
        return RateLimitDecision(
            allowed=bool(allowed),
            limit=rule.limit,
            remaining=remaining,
            # Round up: a 0-second Retry-After would invite an immediate pointless retry.
            retry_after_seconds=max(1, -(-retry_ms // 1000)) if not allowed else 0,
        )


_limiter: SlidingWindowRateLimiter | None = None


def get_rate_limiter() -> SlidingWindowRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowRateLimiter(get_redis())
    return _limiter


def reset_rate_limiter() -> None:
    """Drop the cached limiter so a test can rebuild it against a different Redis."""
    global _limiter
    _limiter = None


def resolve_rule(name: RuleName, settings: RateLimitSettings) -> RateLimitRule:
    limit, window = {
        RuleName.AUTH_LOGIN_IP: (settings.login_ip_limit, settings.login_ip_window_seconds),
        RuleName.AUTH_LOGIN_ACCOUNT: (
            settings.login_account_limit,
            settings.login_account_window_seconds,
        ),
        RuleName.AUTH_REGISTER_IP: (
            settings.register_ip_limit,
            settings.register_ip_window_seconds,
        ),
        RuleName.AUTH_REFRESH_IP: (settings.refresh_ip_limit, settings.refresh_ip_window_seconds),
        RuleName.AUTH_PASSWORD_RESET_IP: (
            settings.password_reset_ip_limit,
            settings.password_reset_ip_window_seconds,
        ),
        RuleName.AUTH_PASSWORD_RESET_ACCOUNT: (
            settings.password_reset_account_limit,
            settings.password_reset_account_window_seconds,
        ),
    }[name]
    policy = FailurePolicy.FAIL_OPEN if settings.fail_open else FailurePolicy.FAIL_CLOSED
    return RateLimitRule(limit=limit, window_seconds=window, policy=policy)


def client_ip(request: Request, trusted_proxy_count: int) -> str:
    """The caller's IP, taken from the socket unless proxies are explicitly trusted.

    `X-Forwarded-For` is attacker-controlled: anyone can send one. Honouring it blindly
    would make every per-IP bucket trivially bypassable by rotating a header value, so
    it is ignored entirely unless `RATE_LIMIT_TRUSTED_PROXY_COUNT` says how many proxies
    actually sit in front of the app. With N trusted proxies, the client address is the
    Nth entry from the right — the last N were appended by infrastructure we control,
    and anything further left was supplied by the caller and cannot be trusted.
    """
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
            if len(hops) >= trusted_proxy_count:
                return hops[-trusted_proxy_count]
    return request.client.host if request.client else "unknown"


def _digest(value: str, secret: str) -> str:
    """Keyed digest of an identity value.

    Keyed rather than a bare hash so the mapping cannot be reversed by anyone who can
    read Redis — buckets are counted per email address, and those should not sit in the
    cache in plaintext or as a rainbow-table-able hash. Truncated to 32 hex chars: still
    128 bits, and collisions here would only merge two callers' buckets, not leak anything.
    """
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def build_key(rule: RuleName, source: IdentitySource, identity: str, secret: str) -> str:
    return f"{KEY_PREFIX}:{rule.value}:{source.value}:{_digest(identity, secret)}"


async def _resolve_identity(
    request: Request, source: IdentitySource, settings: Settings
) -> str | None:
    if source is IdentitySource.IP:
        return client_ip(request, settings.rate_limit.trusted_proxy_count)

    # ACCOUNT_EMAIL. Starlette caches the body on first read, so consuming it here
    # does not stop the route from parsing the same request.
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    email = body.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    # Normalized so casing/whitespace variants share one bucket rather than granting
    # a fresh quota per spelling.
    return email.strip().lower()


# Declared on throttled routes so the generated OpenAPI advertises the 429 rather than
# leaving clients to discover it at runtime. The handler in `core/errors.py` is what
# actually produces the body; this only describes it.
RATE_LIMITED_RESPONSE: dict[int | str, dict[str, object]] = {
    429: {
        "description": (
            "Rate limit exceeded. Retry after `retry_after_seconds` "
            "(also sent as the standard `Retry-After` header)."
        ),
        "model": ProblemDetail,
    }
}


class RateLimitGuard:
    """A FastAPI dependency enforcing one or more buckets on a route.

    Declared in the route's `dependencies=[...]`, so the handler stays free of
    rate-limit code and the limits for an endpoint are visible at its definition.
    """

    def __init__(self, *specs: tuple[RuleName, IdentitySource]) -> None:
        self._specs = specs

    async def __call__(self, request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit.enabled:
            return

        limiter = get_rate_limiter()
        for rule_name, source in self._specs:
            identity = await _resolve_identity(request, source, settings)
            if identity is None:
                # No identity to count against (e.g. a malformed body with no email).
                # The request still faces this endpoint's per-IP bucket, and schema
                # validation rejects it moments later.
                continue

            rule = resolve_rule(rule_name, settings.rate_limit)
            key = build_key(rule_name, source, identity, settings.auth.jwt_secret_value)

            try:
                decision = await limiter.check(key=key, rule=rule)
            except RedisError as exc:
                logger.warning(
                    "rate_limit_backend_unavailable",
                    rule=rule_name.value,
                    policy=rule.policy.value,
                    error=str(exc),
                )
                if rule.policy is FailurePolicy.FAIL_CLOSED:
                    raise RateLimitedError(
                        "Rate limiting is temporarily unavailable. Please retry shortly.",
                        retry_after_seconds=rule.window_seconds,
                    ) from exc
                continue

            if not decision.allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    rule=rule_name.value,
                    route=request.url.path,
                    limit=decision.limit,
                )
                raise RateLimitedError(
                    "Too many requests. Please slow down and try again shortly.",
                    retry_after_seconds=decision.retry_after_seconds,
                )
