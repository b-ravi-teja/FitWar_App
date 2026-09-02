"""Media retention sweep (Architecture §7, §33).

Run periodically — cron, a Kubernetes CronJob, `docker compose exec`, anything that can
invoke a command on a schedule. Deliberately *not* a distributed worker framework: the
project has no queue infrastructure, and §7 asks for the smallest explicit mechanism that
is testable and configurable rather than a new piece of architecture.

Separated from request handling on purpose — deleting objects is not something a user's
HTTP request should wait on, and a sweep that overruns must not slow the API.

    python -m app.workers.media_cleanup

Safe to run repeatedly and safe after a partial failure: `MediaService.run_cleanup` is
idempotent, skips anything already deleted, and structurally cannot touch a video whose
proof is still pending review.
"""

import asyncio

from app.core.database import _session_factory
from app.core.logging import configure_logging, get_logger
from app.services.media_service import MediaService

logger = get_logger(__name__)


async def run_once() -> int:
    """One sweep. Returns how many objects were deleted."""
    async with _session_factory() as session:
        deleted = await MediaService(session).run_cleanup()
        await session.commit()
    logger.info("media_cleanup_completed", deleted=deleted)
    return deleted


def main() -> None:
    configure_logging()
    deleted = asyncio.run(run_once())
    print(f"media cleanup: {deleted} object(s) deleted")


if __name__ == "__main__":
    main()
