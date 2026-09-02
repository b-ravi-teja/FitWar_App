import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class GroupPrivacy(enum.StrEnum):
    """`public` is persisted-but-dormant in V1 — no discovery API reads it (ADR 0001)."""

    INVITE = "invite"
    PUBLIC = "public"


class GroupRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class GroupMemberStatus(enum.StrEnum):
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class Group(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "group"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # IANA identifier, never a fixed UTC offset — the frozen authority every challenge
    # in this group snapshots its daily boundary from (Architecture §11).
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    privacy: Mapped[GroupPrivacy] = mapped_column(
        SAEnum(GroupPrivacy, name="group_privacy", native_enum=False, length=16),
        default=GroupPrivacy.INVITE,
        nullable=False,
    )
    # The invite mechanism itself, rather than a separate Invite table: the design's
    # create-challenge flow shows one shareable code per squad, and a column satisfies
    # that without standalone invite infrastructure.
    join_code: Mapped[str] = mapped_column(String(12), unique=True, index=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    members: Mapped[list["GroupMember"]] = relationship(back_populates="group")


class GroupMember(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member_group_user"),
        Index("ix_group_member_user_status", "user_id", "status"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("group.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    role: Mapped[GroupRole] = mapped_column(
        SAEnum(GroupRole, name="group_role", native_enum=False, length=16),
        default=GroupRole.MEMBER,
        nullable=False,
    )
    status: Mapped[GroupMemberStatus] = mapped_column(
        SAEnum(GroupMemberStatus, name="group_member_status", native_enum=False, length=16),
        default=GroupMemberStatus.ACTIVE,
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    group: Mapped["Group"] = relationship(back_populates="members")
