"""AuthService business-rule tests against fake repositories — no database involved.

This is where register/login/refresh/logout's actual decisions get their heaviest
coverage, because they're pure orchestration logic and should run in milliseconds.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import hash_password, hash_refresh_token
from app.domain.auth.exceptions import (
    AccountDeletedError,
    EmailAlreadyTakenError,
    InvalidCredentialsError,
    RefreshTokenInvalidError,
    RefreshTokenReuseDetectedError,
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

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        for token in self.by_hash.values():
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)


@pytest.fixture
def auth_service() -> AuthService:
    service = AuthService.__new__(AuthService)  # bypass __init__ (no real session)
    service._users = FakeUserRepository()
    service._refresh_tokens = FakeRefreshTokenRepository()
    return service


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
