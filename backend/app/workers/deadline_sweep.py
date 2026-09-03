"""Periodic deadline resolution (Architecture §20.5, §22.5).

Phase 5 resolves deadlines **lazily**: any read or write that touches a challenge sweeps
it first. That keeps the rules deterministic for anyone who opens the app, and it is not
enough on its own — a participant who simply stops opening FITWAR would never accrue the
misses that produce a warning or an elimination, so the failure rule would quietly depend
on the victim showing up to be eliminated.

This runs the same operation on a schedule so resolution happens whether or not anybody
looks. It calls exactly the Phase 5 code path (`GameService.resolve_overdue_days` +
`finalize_if_ended`) rather than reimplementing any rule — the sweep decides *when* to
ask, never *what* the answer is.

    python -m app.workers.deadline_sweep

Safe to run repeatedly, concurrently with itself, and alongside live traffic:

- `resolve_overdue_days` only moves a day from PENDING, so a second pass is a read.
- `UNIQUE(participant, challenge_day)` on `warning` and `UNIQUE(participant)` on
  `elimination` make duplicates impossible even if two sweeps overlap.
- `finalize_if_ended` never rewrites an outcome that is already set.
- Each challenge commits in its own transaction, so one failure cannot roll back the
  challenges already resolved, and a crash mid-sweep simply resumes next run.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.database import _session_factory
from app.core.logging import configure_logging, get_logger
from app.repositories.challenges import ChallengeRepository
from app.services.challenge_service import ChallengeService
from app.services.game_service import GameService

logger = get_logger(__name__)

# Upper bound on challenges touched per run. A sweep that cannot finish in its interval
# should fall behind visibly rather than hold transactions open indefinitely; the next
# run picks up where this one stopped.
DEFAULT_BATCH_LIMIT = 500


@dataclass(frozen=True)
class SweepResult:
    challenges_visited: int
    days_resolved: int
    challenges_finalized: int
    failures: int


async def _sweep_one(challenge_id: uuid.UUID, now: datetime) -> tuple[int, bool]:
    """Resolve one challenge in its own transaction. Returns (days resolved, finalized)."""
    async with _session_factory() as session:
        challenges = ChallengeService(session)
        game = GameService(session)
        challenge = await ChallengeRepository(session).get_by_id(challenge_id)
        if challenge is None:  # deleted between listing and processing
            return 0, False
        # Advance DRAFT→ACTIVE / ACTIVE→COMPLETED first: a challenge whose window has
        # closed has to be COMPLETED before its outcomes can be written.
        await challenges.sync_status(challenge, now=now)
        resolved = await game.resolve_overdue_days(challenge, now=now)
        finalized = await game.finalize_if_ended(challenge, now=now)
        await session.commit()
        return resolved, finalized


async def run_once(*, now: datetime | None = None, limit: int = DEFAULT_BATCH_LIMIT) -> SweepResult:
    now = now or datetime.now(UTC)
    async with _session_factory() as session:
        challenge_ids = await ChallengeRepository(session).list_resolvable(now, limit=limit)

    days = finalized = failures = 0
    for challenge_id in challenge_ids:
        try:
            resolved, closed = await _sweep_one(challenge_id, now)
        except Exception as exc:
            # One bad challenge must not stop the sweep. Logged with its id so it can
            # actually be investigated rather than silently skipped forever.
            failures += 1
            logger.exception(
                "deadline_sweep_challenge_failed",
                challenge_id=str(challenge_id),
                error=str(exc),
            )
            continue
        days += resolved
        finalized += int(closed)

    result = SweepResult(
        challenges_visited=len(challenge_ids),
        days_resolved=days,
        challenges_finalized=finalized,
        failures=failures,
    )
    logger.info(
        "deadline_sweep_completed",
        challenges_visited=result.challenges_visited,
        days_resolved=result.days_resolved,
        challenges_finalized=result.challenges_finalized,
        failures=result.failures,
    )
    return result


def main() -> None:
    configure_logging()
    result = asyncio.run(run_once())
    print(
        f"deadline sweep: visited {result.challenges_visited}, "
        f"resolved {result.days_resolved} day(s), "
        f"finalized {result.challenges_finalized}, failures {result.failures}"
    )
    raise SystemExit(1 if result.failures else 0)


if __name__ == "__main__":
    main()
