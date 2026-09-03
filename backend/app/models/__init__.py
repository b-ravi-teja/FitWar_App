"""SQLAlchemy ORM models. Import every model module here so Alembic autogenerate sees them."""

from app.models.auth import RefreshToken
from app.models.battle import (
    Battle,
    BattleParticipant,
    BattleParticipantStatus,
    BattleStatus,
)
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeRule,
    DailyChallengeProgress,
)
from app.models.game import Elimination, Warning, XPReason, XPTransaction
from app.models.group import Group, GroupMember
from app.models.media import (
    GroupMessage,
    MediaAsset,
    MediaContextType,
    MediaStatus,
    MediaVisibility,
    MessageReaction,
    MessageType,
)
from app.models.user import User, UserProfile
from app.models.verification import (
    HealthConnection,
    HealthConnectionStatus,
    HealthProvider,
    VerificationRecord,
    VerificationStatus,
)

__all__ = [
    "Battle",
    "BattleParticipant",
    "BattleParticipantStatus",
    "BattleStatus",
    "Challenge",
    "ChallengeParticipant",
    "ChallengeRule",
    "DailyChallengeProgress",
    "Elimination",
    "Group",
    "GroupMember",
    "GroupMessage",
    "HealthConnection",
    "HealthConnectionStatus",
    "HealthProvider",
    "MediaAsset",
    "MediaContextType",
    "MediaStatus",
    "MediaVisibility",
    "MessageReaction",
    "MessageType",
    "RefreshToken",
    "User",
    "UserProfile",
    "VerificationRecord",
    "VerificationStatus",
    "Warning",
    "XPReason",
    "XPTransaction",
]
