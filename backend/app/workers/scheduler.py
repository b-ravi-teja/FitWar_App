"""The periodic-job runner (Architecture §35).

FITWAR has no queue infrastructure and this phase is not the place to introduce any, so
scheduling is the smallest mechanism that actually fits the deployment: one long-running
container that invokes the existing worker entry points on an interval. Each job is the
same callable `python -m app.workers.<job>` runs, so "scheduled" and "run it by hand"
cannot drift apart.

Why a loop in a container rather than system cron:

- The image already has the app, its dependencies and its configuration; cron would need
  a second copy of all three.
- It deploys identically everywhere the API deploys (Compose, ECS, a Kubernetes
  Deployment) with no host-level state.
- A platform-native scheduler is still a drop-in alternative — a Kubernetes CronJob or
  ECS scheduled task can call `python -m app.workers.deadline_sweep` directly and this
  process simply isn't deployed. That is why the workers stay independently runnable.

Every job here must be idempotent and safe to run concurrently with itself, because
nothing prevents two scheduler replicas from overlapping: correctness comes from the
database constraints the jobs rely on, never from there being exactly one runner.

    python -m app.workers.scheduler
"""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.workers import deadline_sweep, media_cleanup

logger = get_logger(__name__)


@dataclass(frozen=True)
class Job:
    name: str
    interval_seconds: int
    run: Callable[[], Awaitable[object]]


async def _run_forever(job: Job, stop: asyncio.Event) -> None:
    """Run one job on its interval until asked to stop.

    A failing job logs and waits for its next tick rather than killing the process — one
    broken sweep must not also stop media retention, and a crash-looping container would
    turn a recoverable error into an outage.
    """
    while not stop.is_set():
        try:
            await job.run()
        except Exception as exc:
            logger.exception("scheduled_job_failed", job=job.name, error=str(exc))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=job.interval_seconds)


async def run(stop: asyncio.Event | None = None) -> None:
    settings = get_settings().scheduler
    stop = stop or asyncio.Event()

    jobs = [
        Job(
            name="deadline_sweep",
            interval_seconds=settings.deadline_sweep_interval_seconds,
            run=deadline_sweep.run_once,
        ),
        Job(
            name="media_cleanup",
            interval_seconds=settings.media_cleanup_interval_seconds,
            run=media_cleanup.run_once,
        ),
    ]
    enabled = [job for job in jobs if job.name not in settings.disabled_jobs]
    logger.info(
        "scheduler_started",
        jobs={job.name: job.interval_seconds for job in enabled},
        disabled=sorted(settings.disabled_jobs),
    )
    await asyncio.gather(*(_run_forever(job, stop) for job in enabled))
    logger.info("scheduler_stopped")


def main() -> None:
    configure_logging()
    stop = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Graceful shutdown: finish the job in flight, then exit, so a deploy can
            # never interrupt a sweep mid-transaction.
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        await run(stop)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
