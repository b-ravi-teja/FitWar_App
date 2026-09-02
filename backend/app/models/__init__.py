"""SQLAlchemy ORM models. Import every model module here so Alembic autogenerate sees them."""

from app.models.auth import RefreshToken
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeRule,
    DailyChallengeProgress,
)
from app.models.group import Group, GroupMember
from app.models.user import User, UserProfile
from app.models.verification import (
    HealthConnection,
    HealthConnectionStatus,
    HealthProvider,
    VerificationRecord,
    VerificationStatus,
)

__all__ = [
    "Challenge",
    "ChallengeParticipant",
    "ChallengeRule",
    "DailyChallengeProgress",
    "Group",
    "GroupMember",
    "HealthConnection",
    "HealthConnectionStatus",
    "HealthProvider",
    "RefreshToken",
    "User",
    "UserProfile",
    "VerificationRecord",
    "VerificationStatus",
]
