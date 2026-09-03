"""AuthService business-rule tests against fake repositories — no database involved.

This is where register/login/refresh/logout's actual decisions get their heaviest
coverage, because they're pure orchestration logic and should run in milliseconds.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from app.core.security import hash_password, hash_refresh_token
from app.domain.auth.exceptions import (
    AccountDeletedError,
    EmailAlreadyTakenError,
    InvalidCredentialsError,
    RefreshTokenInvalidError,
    RefreshTokenReuseDetectedError,
    ResetTokenInvalidError,
)
from app.models.auth import RefreshToken
from app.models.user import User, UserProfile, UserStatus
from app.services.auth_service import AuthService


class FakeUserRepository:
    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, User] = {}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.by_id.values() if u.email == email), None)

    async def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        user = User(
            id=uuid.uuid4(), email=email, password_hash=password_hash, status=UserStatus.ACTIVE
        )
        user.profile = UserProfile(user_id=user.id, display_name=display_name)
        self.by_id[user.id] = user
        return user

    async def soft_delete(self, user: User) -> None:
        user.status = UserStatus.DELETED
        user.deleted_at = datetime.now(UTC)

    async def update_password_hash(self, user: User, *, password_hash: str) -> None:
        user.password_hash = password_hash


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self.by_hash: dict[str, RefreshToken] = {}

    async def create(
        self, *, user_id: uuid.UUID, token_hash: str, family_id: uuid.UUID, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )
        self.by_hash[token_hash] = token
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.by_hash.get(token_hash)

    async def revoke(self, token: RefreshToken) -> bool:
        """Mirrors the real conditional UPDATE: only the caller that actually flips
        `revoked_at` reports True, so a second rotation of the same token is refused."""
        if token.revoked_at is not None:
            return False
        token.revoked_at = datetime.now(UTC)
        return True

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        for token in self.by_hash.values():
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        for token in self.by_hash.values():
            if token.user_id == user_id and token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)


class FakePasswordResetTokenRepository:
    def __init__(self) -> None:
        self.by_token: dict[str, uuid.UUID] = {}

    async def store(self, *, raw_token: str, user_id: uuid.UUID) -> None:
        self.by_token[raw_token] = user_id

    async def consume(self, raw_token: str) -> uuid.UUID | None:
        return self.by_token.pop(raw_token, None)


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_password_reset(self, *, to: str, token: str) -> None:
        self.sent.append((to, token))


class FakeSession:
    """Just enough session for `AuthService`.

    `commit` matters: reuse detection revokes the token family and commits it *before*
    raising, because the request transaction is rolled back on the way out and the
    revocation would otherwise be discarded (the P0 this suite now covers).
    """

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def auth_service() -> AuthService:
    service = AuthService.__new__(AuthService)  # bypass __init__ (no real session)
    service._session = cast(Any, FakeSession())
    service._users = FakeUserRepository()
    service._refresh_tokens = FakeRefreshTokenRepository()
    service._reset_tokens = FakePasswordResetTokenRepository()
    service._email_sender = FakeEmailSender()
    return service


def _fake_email_sender(service: AuthService) -> FakeEmailSender:
    """The service depends on the `EmailSender` protocol, which has no `.sent` —
    this recovers the concrete fake so tests can inspect what was "sent"."""
    return cast(FakeEmailSender, service._email_sender)


def _fake_reset_tokens(service: AuthService) -> FakePasswordResetTokenRepository:
    return cast(FakePasswordResetTokenRepository, service._reset_tokens)


async def test_register_creates_user_and_tokens(auth_service: AuthService) -> None:
    user, tokens = await auth_service.register(
        email="ravi@example.com", password="hunter22", display_name="Ravi"
    )
    assert user.email == "ravi@example.com"
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in == 15 * 60


async def test_register_duplicate_email_raises(auth_service: AuthService) -> None:
    await auth_service.register(email="dup@example.com", password="hunter22", display_name="A")
    with pytest.raises(EmailAlreadyTakenError):
        await auth_service.register(email="dup@example.com", password="other123", display_name="B")


async def test_login_valid_credentials(auth_service: AuthService) -> None:
    await auth_service.register(email="ravi@example.com", password="hunter22", display_name="Ravi")
    user, tokens = await auth_service.login(email="ravi@example.com", password="hunter22")
    assert user.email == "ravi@example.com"
    assert tokens.access_token


async def test_login_wrong_password_raises(auth_service: AuthService) -> None:
    await auth_service.register(email="ravi@example.com", password="hunter22", display_name="Ravi")
    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(email="ravi@example.com", password="wrong-password")


async def test_login_unknown_email_raises(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentialsError):
        await auth_service.login(email="ghost@example.com", password="whatever1")


async def test_login_deleted_account_raises(auth_service: AuthService) -> None:
    user, _ = await auth_service.register(
        email="gone@example.com", password="hunter22", display_name="G"
    )
    await auth_service._users.soft_delete(user)
    with pytest.raises(AccountDeletedError):
        await auth_service.login(email="gone@example.com", password="hunter22")


async def test_refresh_valid_token_rotates(auth_service: AuthService) -> None:
    _, tokens = await auth_service.register(
        email="ravi@example.com", password="hunter22", display_name="R"
    )
    new_tokens = await auth_service.refresh(raw_refresh_token=tokens.refresh_token)
    assert new_tokens.refresh_token != tokens.refresh_token
    assert new_tokens.access_token


async def test_refresh_unrecognized_token_raises(auth_service: AuthService) -> None:
    with pytest.raises(RefreshTokenInvalidError):
        await auth_service.refresh(raw_refresh_token="not-a-real-token")


async def test_refresh_expired_token_raises(auth_service: AuthService) -> None:
    user, _ = await auth_service.register(
        email="ravi@example.com", password="hunter22", display_name="R"
    )
    expired_raw = "expired-raw-token"
    await auth_service._refresh_tokens.create(
        user_id=user.id,
        token_hash=hash_refresh_token(expired_raw),
        family_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    with pytest.raises(RefreshTokenInvalidError):
        await auth_service.refresh(raw_refresh_token=expired_raw)


async def test_refresh_reuse_of_revoked_token_revokes_family(auth_service: AuthService) -> None:
    _, tokens = await auth_service.register(
        email="ravi@example.com", password="hunter22", display_name="R"
    )
    first_refresh = tokens.refresh_token

    # Legitimate rotation: the original token is now revoked.
    rotated = await auth_service.refresh(raw_refresh_token=first_refresh)

    # An attacker (or a retried request) replays the already-rotated token.
    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=first_refresh)

    # The whole family — including the token issued by the legitimate rotation — is dead.
    # It's found (not unrecognized) but revoked, so this is reuse, not "invalid".
    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=rotated.refresh_token)


async def test_logout_revokes_token(auth_service: AuthService) -> None:
    _, tokens = await auth_service.register(
        email="ravi@example.com", password="hunter22", display_name="R"
    )
    await auth_service.logout(raw_refresh_token=tokens.refresh_token)
    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=tokens.refresh_token)


async def test_logout_unknown_token_is_a_noop(auth_service: AuthService) -> None:
    await auth_service.logout(raw_refresh_token="never-issued")


def test_password_hash_helper_is_argon2() -> None:
    assert hash_password("x").startswith("$argon2")


async def test_request_password_reset_for_existing_email_stores_token_and_sends_email(
    auth_service: AuthService,
) -> None:
    await auth_service.register(email="ravi@example.com", password="hunter22", display_name="R")

    await auth_service.request_password_reset(email="ravi@example.com")

    sent = _fake_email_sender(auth_service).sent
    assert len(sent) == 1
    to, token = sent[0]
    assert to == "ravi@example.com"
    assert token in _fake_reset_tokens(auth_service).by_token


async def test_request_password_reset_for_unknown_email_is_a_silent_noop(
    auth_service: AuthService,
) -> None:
    """Never reveals whether the account exists (ADR 0007) — same outward behavior
    (no exception, no email sent) as a real account, just nothing happens."""
    await auth_service.request_password_reset(email="ghost@example.com")
    assert _fake_email_sender(auth_service).sent == []


async def test_confirm_password_reset_updates_password_and_revokes_sessions(
    auth_service: AuthService,
) -> None:
    _, tokens = await auth_service.register(
        email="ravi@example.com", password="oldpassword1", display_name="R"
    )
    await auth_service.request_password_reset(email="ravi@example.com")
    _, raw_token = _fake_email_sender(auth_service).sent[0]

    await auth_service.confirm_password_reset(token=raw_token, new_password="newpassword1")

    # Old session is dead...
    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=tokens.refresh_token)
    # ...and the new password actually works.
    _, new_tokens = await auth_service.login(email="ravi@example.com", password="newpassword1")
    assert new_tokens.access_token


async def test_confirm_password_reset_token_is_single_use(auth_service: AuthService) -> None:
    await auth_service.register(email="ravi@example.com", password="oldpassword1", display_name="R")
    await auth_service.request_password_reset(email="ravi@example.com")
    _, raw_token = _fake_email_sender(auth_service).sent[0]

    await auth_service.confirm_password_reset(token=raw_token, new_password="newpassword1")

    with pytest.raises(ResetTokenInvalidError):
        await auth_service.confirm_password_reset(token=raw_token, new_password="anotherpassword1")


async def test_confirm_password_reset_unrecognized_token_raises(auth_service: AuthService) -> None:
    with pytest.raises(ResetTokenInvalidError):
        await auth_service.confirm_password_reset(token="never-issued", new_password="newpassword1")


async def test_reuse_detection_commits_the_family_revocation(
    auth_service: AuthService,
) -> None:
    """P0 regression: the revocation used to be rolled back with the request.

    `AuthService.refresh` revoked the family and then raised; the request's transaction
    is rolled back on any exception, so the theft response never persisted. The commit
    is the fix, and this asserts it happens rather than only that the error is raised.
    """
    _, tokens = await auth_service.register(
        email="reuse@example.com", password="hunter22", display_name="R"
    )
    rotated = await auth_service.refresh(raw_refresh_token=tokens.refresh_token)

    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=tokens.refresh_token)

    session = cast(Any, auth_service)._session
    assert session.commits >= 1, "family revocation was not committed before raising"
    # And the legitimate holder's current token is dead too — the point of a family.
    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=rotated.refresh_token)


async def test_a_token_cannot_be_rotated_twice_even_without_a_prior_revocation(
    auth_service: AuthService,
) -> None:
    """Rotation is decided by the conditional UPDATE, not by the earlier read.

    Simulates the concurrent case: two callers both pass the `revoked_at is None` check,
    and only the one whose UPDATE actually matched is allowed to mint tokens.
    """
    _, tokens = await auth_service.register(
        email="atomic@example.com", password="hunter22", display_name="A"
    )
    await auth_service.refresh(raw_refresh_token=tokens.refresh_token)

    with pytest.raises(RefreshTokenReuseDetectedError):
        await auth_service.refresh(raw_refresh_token=tokens.refresh_token)
