"""Rate-limiter tests.

Deliberately run against the real Redis from docker-compose rather than a fake. The
whole point of the Lua script is atomicity under concurrency, and a mock that returns
canned values would assert nothing about the property the code exists to guarantee.
Only the Redis-failure tests use a broken client, since that state is otherwise hard
to produce on demand.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import (
    FailurePolicy,
    IdentitySource,
    RateLimitGuard,
    RateLimitRule,
    RuleName,
    SlidingWindowRateLimiter,
    build_key,
    client_ip,
    reset_rate_limiter,
)
from app.core.redis import get_redis
from app.domain.common.exceptions import RateLimitedError
from app.main import create_app


@pytest.fixture
def limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(get_redis())


@pytest.fixture
def key() -> str:
    # Unique per test so buckets never collide across tests.
    return f"rl:v1:test:{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Core window behaviour
# ---------------------------------------------------------------------------


async def test_requests_under_the_limit_are_allowed(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    rule = RateLimitRule(limit=3, window_seconds=60)

    first = await limiter.check(key=key, rule=rule)
    second = await limiter.check(key=key, rule=rule)

    assert first.allowed and second.allowed
    # Remaining counts down so a caller can see how much budget is left.
    assert (first.remaining, second.remaining) == (2, 1)


async def test_request_at_the_limit_is_still_allowed(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    """The Nth request of a limit-N rule must succeed — the limit is inclusive."""
    rule = RateLimitRule(limit=3, window_seconds=60)

    decisions = [await limiter.check(key=key, rule=rule) for _ in range(3)]

    assert all(d.allowed for d in decisions)
    assert decisions[-1].remaining == 0


async def test_request_over_the_limit_is_denied_with_retry_information(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    rule = RateLimitRule(limit=2, window_seconds=60)
    for _ in range(2):
        await limiter.check(key=key, rule=rule)

    denied = await limiter.check(key=key, rule=rule)

    assert not denied.allowed
    assert denied.remaining == 0
    # Retry-after points at when the oldest entry ages out, so it never exceeds the
    # window and is never a useless zero.
    assert 0 < denied.retry_after_seconds <= 60


async def test_window_expiry_restores_the_budget(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    rule = RateLimitRule(limit=1, window_seconds=1)
    assert (await limiter.check(key=key, rule=rule)).allowed
    assert not (await limiter.check(key=key, rule=rule)).allowed

    await asyncio.sleep(1.1)

    assert (await limiter.check(key=key, rule=rule)).allowed


async def test_denied_requests_do_not_extend_the_lockout(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    """A caller who keeps hammering while blocked must still be freed on schedule.

    If rejected attempts were recorded, each one would push the window forward and the
    caller could never get back in — a self-inflicted permanent ban.
    """
    rule = RateLimitRule(limit=1, window_seconds=1)
    await limiter.check(key=key, rule=rule)
    for _ in range(5):
        assert not (await limiter.check(key=key, rule=rule)).allowed

    await asyncio.sleep(1.1)

    assert (await limiter.check(key=key, rule=rule)).allowed


# ---------------------------------------------------------------------------
# Bucket separation
# ---------------------------------------------------------------------------


async def test_separate_keys_have_independent_budgets(
    limiter: SlidingWindowRateLimiter,
) -> None:
    """Two different callers, or two different endpoints, must not share a budget."""
    rule = RateLimitRule(limit=1, window_seconds=60)
    first, second = f"rl:v1:test:{uuid.uuid4().hex}", f"rl:v1:test:{uuid.uuid4().hex}"

    assert (await limiter.check(key=first, rule=rule)).allowed
    assert not (await limiter.check(key=first, rule=rule)).allowed
    # Exhausting one bucket leaves the other untouched.
    assert (await limiter.check(key=second, rule=rule)).allowed


def test_key_strategy_separates_rules_identities_and_sources() -> None:
    secret = "test-secret"
    login_a = build_key(RuleName.AUTH_LOGIN_IP, IdentitySource.IP, "1.2.3.4", secret)
    login_b = build_key(RuleName.AUTH_LOGIN_IP, IdentitySource.IP, "5.6.7.8", secret)
    register_a = build_key(RuleName.AUTH_REGISTER_IP, IdentitySource.IP, "1.2.3.4", secret)
    account_a = build_key(
        RuleName.AUTH_LOGIN_ACCOUNT, IdentitySource.ACCOUNT_EMAIL, "1.2.3.4", secret
    )

    assert len({login_a, login_b, register_a, account_a}) == 4
    # The identity never appears in the key — Redis holds a keyed digest, not the
    # caller's email address or IP.
    assert "1.2.3.4" not in login_a


def test_digest_is_keyed_so_identities_cannot_be_reversed_without_the_secret() -> None:
    a = build_key(RuleName.AUTH_LOGIN_IP, IdentitySource.IP, "1.2.3.4", "secret-one")
    b = build_key(RuleName.AUTH_LOGIN_IP, IdentitySource.IP, "1.2.3.4", "secret-two")
    assert a != b


# ---------------------------------------------------------------------------
# Concurrency — the property the Lua script exists to guarantee
# ---------------------------------------------------------------------------


async def test_concurrent_requests_cannot_exceed_the_limit(
    limiter: SlidingWindowRateLimiter, key: str
) -> None:
    """50 simultaneous requests against a limit of 5 must yield exactly 5 allowances.

    A read-then-write limiter would let many of these interleave between ZCARD and
    ZADD and all pass. This is the test that would catch that.
    """
    rule = RateLimitRule(limit=5, window_seconds=60)

    decisions = await asyncio.gather(*(limiter.check(key=key, rule=rule) for _ in range(50)))

    assert sum(1 for d in decisions if d.allowed) == 5


# ---------------------------------------------------------------------------
# Redis failure policy
# ---------------------------------------------------------------------------


@pytest.fixture
def broken_limiter() -> SlidingWindowRateLimiter:
    """A limiter pointed at a port nothing is listening on."""
    return SlidingWindowRateLimiter(Redis.from_url("redis://127.0.0.1:6399/0"))


async def test_fail_closed_rejects_when_redis_is_unreachable(
    broken_limiter: SlidingWindowRateLimiter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auth endpoints must not silently lose protection because Redis went away."""
    monkeypatch.setattr("app.core.rate_limit.get_rate_limiter", lambda: broken_limiter)
    guard = RateLimitGuard((RuleName.AUTH_LOGIN_IP, IdentitySource.IP))

    with pytest.raises(RateLimitedError) as exc_info:
        await guard(_fake_request())

    assert exc_info.value.code == "RATE_LIMITED"
    # The client is told to retry, never why it failed — no Redis detail escapes.
    assert exc_info.value.retry_after_seconds is not None
    assert "redis" not in str(exc_info.value.detail).lower()


async def test_fail_open_allows_when_redis_is_unreachable(
    broken_limiter: SlidingWindowRateLimiter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.rate_limit.get_rate_limiter", lambda: broken_limiter)
    settings = get_settings()
    monkeypatch.setattr(settings.rate_limit, "fail_open", True)
    guard = RateLimitGuard((RuleName.AUTH_LOGIN_IP, IdentitySource.IP))

    await guard(_fake_request())  # must not raise


def test_failure_policy_follows_the_fail_open_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.rate_limit import resolve_rule

    settings = get_settings()
    monkeypatch.setattr(settings.rate_limit, "fail_open", False)
    assert resolve_rule(RuleName.AUTH_LOGIN_IP, settings.rate_limit).policy is (
        FailurePolicy.FAIL_CLOSED
    )


# ---------------------------------------------------------------------------
# Client identity resolution
# ---------------------------------------------------------------------------


def _fake_request(headers: dict[str, str] | None = None, peer: str = "10.0.0.1"):  # type: ignore[no-untyped-def]
    from starlette.datastructures import Headers
    from starlette.requests import Request

    raw = Headers(headers or {}).raw
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "raw_path": b"/api/v1/auth/login",
            "query_string": b"",
            "headers": raw,
            "client": (peer, 51234),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def test_forwarded_header_is_ignored_when_no_proxy_is_trusted() -> None:
    """Otherwise any caller could reset their own bucket by inventing a header."""
    request = _fake_request({"x-forwarded-for": "9.9.9.9"}, peer="10.0.0.1")
    assert client_ip(request, trusted_proxy_count=0) == "10.0.0.1"


def test_forwarded_header_is_used_when_a_proxy_is_trusted() -> None:
    """One trusted proxy in front: it appended the peer it saw, so that entry is the client.

    client 203.0.113.7 → proxy 10.0.0.9 → app. The proxy appends the client address,
    and the app's socket peer is the proxy.
    """
    request = _fake_request({"x-forwarded-for": "203.0.113.7"}, peer="10.0.0.9")
    assert client_ip(request, trusted_proxy_count=1) == "203.0.113.7"


def test_spoofed_hops_beyond_the_trusted_count_are_discarded() -> None:
    """A caller prepending fake hops must not shift which entry is read.

    The client sent its own `X-Forwarded-For: 1.1.1.1` hoping to be counted as a
    different caller; the trusted proxy then appended the address it actually saw.
    Reading one hop from the right picks the proxy's observation, never the forgery.
    """
    request = _fake_request({"x-forwarded-for": "1.1.1.1, 203.0.113.7"}, peer="10.0.0.9")
    assert client_ip(request, trusted_proxy_count=1) == "203.0.113.7"


def test_forwarded_header_falls_back_to_peer_when_it_has_too_few_hops() -> None:
    """Fewer hops than trusted proxies means the header is not what we expect — a
    misconfiguration or a stripped header — so the socket peer wins rather than a guess."""
    request = _fake_request({"x-forwarded-for": "1.1.1.1"}, peer="10.0.0.9")
    assert client_ip(request, trusted_proxy_count=3) == "10.0.0.9"


# ---------------------------------------------------------------------------
# End-to-end through the API
# ---------------------------------------------------------------------------


@pytest.fixture
async def tight_login_client(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncClient:
    """A client whose login limit is 3, so the 429 path is reachable in a test."""
    settings = get_settings()
    monkeypatch.setattr(settings.rate_limit, "login_ip_limit", 3)
    monkeypatch.setattr(settings.rate_limit, "login_ip_window_seconds", 60)
    reset_rate_limiter()

    app = create_app()

    async def _override_get_db():  # type: ignore[no-untyped-def]
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_login_returns_429_problem_details_once_the_limit_is_passed(
    tight_login_client: AsyncClient,
) -> None:
    payload = {"email": "nobody@example.com", "password": "wrong-password-here"}

    async with tight_login_client as client:
        for _ in range(3):
            # Wrong credentials still consume budget — that is the point.
            assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401

        response = await client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["status"] == 429
    assert set(body) >= {"type", "title", "status", "detail", "code", "retry_after_seconds"}
    assert body["retry_after_seconds"] > 0
    # Standard header, so clients and proxies can honour it without parsing the body.
    assert response.headers["Retry-After"] == str(body["retry_after_seconds"])
    assert "redis" not in response.text.lower()


async def test_rate_limited_login_does_not_reveal_whether_the_account_exists(
    tight_login_client: AsyncClient, register_actor  # type: ignore[no-untyped-def]
) -> None:
    """The 429 for a real account and an unknown one must be indistinguishable."""
    async with tight_login_client as client:
        actor_email = f"real-{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={"email": actor_email, "password": "hunter2222", "display_name": "Real"},
        )

        async def exhaust(email: str) -> dict[str, object]:
            payload = {"email": email, "password": "definitely-wrong"}
            last = None
            for _ in range(5):
                last = await client.post("/api/v1/auth/login", json=payload)
            assert last is not None and last.status_code == 429
            return dict(last.json())

        existing = await exhaust(actor_email)
        missing = await exhaust(f"ghost-{uuid.uuid4().hex[:8]}@example.com")

    # Same code, same title, same detail — nothing separates the two cases.
    assert existing["code"] == missing["code"]
    assert existing["detail"] == missing["detail"]
    assert existing["title"] == missing["title"]


async def test_other_endpoints_keep_their_own_budget(tight_login_client: AsyncClient) -> None:
    """Exhausting login must not throttle registration — separate buckets."""
    async with tight_login_client as client:
        payload = {"email": "nobody@example.com", "password": "wrong-password-here"}
        for _ in range(4):
            await client.post("/api/v1/auth/login", json=payload)

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"fresh-{uuid.uuid4().hex[:8]}@example.com",
                "password": "hunter2222",
                "display_name": "Fresh",
            },
        )

    assert response.status_code == 201
