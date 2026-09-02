"""In-process domain event bus (Architecture §2, §10).

Phase 5 *publishes*; nothing subscribes yet. That is deliberate: §10's realtime fanout,
push notifications and leaderboard cache invalidation are all Phase 6 subscribers to
these same events, and building the WebSocket infrastructure now to justify the publish
would be exactly the premature work the guardrails forbid.

Events are published only after the transaction that produced them commits — a
subscriber must never observe a score change that later rolls back.
"""

import enum
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class EventType(enum.StrEnum):
    VERIFICATION_COMPLETED = "verification_completed"
    SCORE_CHANGED = "score_changed"
    XP_AWARDED = "xp_awarded"
    WARNING_ISSUED = "warning_issued"
    PARTICIPANT_ELIMINATED = "participant_eliminated"
    CHALLENGE_COMPLETED = "challenge_completed"


@dataclass(frozen=True)
class DomainEvent:
    type: EventType
    challenge_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[DomainEvent], None]

_subscribers: dict[EventType, list[Subscriber]] = {}


def subscribe(event_type: EventType, subscriber: Subscriber) -> None:
    _subscribers.setdefault(event_type, []).append(subscriber)


def reset_subscribers() -> None:
    """Test hook — keeps one test's subscriber out of the next one's bus."""
    _subscribers.clear()


def publish(event: DomainEvent) -> None:
    """Fan out to subscribers. A failing subscriber is logged, never raised: a broken
    notification must not roll back a committed competitive result."""
    logger.info(
        "domain_event",
        event_type=event.type.value,
        challenge_id=str(event.challenge_id) if event.challenge_id else None,
    )
    for subscriber in _subscribers.get(event.type, []):
        try:
            subscriber(event)
        except Exception as exc:
            logger.warning(
                "domain_event_subscriber_failed", event_type=event.type.value, error=str(exc)
            )
