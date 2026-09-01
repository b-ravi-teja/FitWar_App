import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """Server-side record enabling rotation + reuse detection (Architecture §6).

    Fields match the frozen ERD (Architecture §4) exactly — no `issued_at` or
    `replaced_by_id` columns, even though an earlier informal draft of the domain
    model (§3.1 prose) mentioned them. Flagged as a documented inconsistency in the
    Phase 1 report rather than silently added: reuse detection only strictly needs
    `revoked_at`, so the leaner ERD shape is sufficient for the security property.
    """

    __tablename__ = "refresh_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
