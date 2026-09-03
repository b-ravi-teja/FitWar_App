# ADR 0010 — Scheduled Background Jobs

## Status
Accepted

## Context
Two operations were implemented correctly and never actually scheduled.

**Deadline resolution.** §20.5 requires that a challenge day whose deadline passes without
a verified completion resolves as `missed`, on schedule, "never blocked on a human".
Phase 5 implemented this as a *lazy* sweep: any read or write touching a challenge
resolves it first. That is deterministic for anyone who opens the app, and it has a hole —
a participant who simply stops opening FITWAR never accrues the misses that produce a
warning or an elimination. The failure rule ends up depending on the person being
eliminated showing up to be eliminated.

**Media retention.** §33 makes storage cost an explicit product constraint and
`app/workers/media_cleanup.py` implements the sweep, documented as "run periodically —
cron, a Kubernetes CronJob, anything". Nothing ran it, so retention never actually
happened.

Phase 8 is a hardening pass, so the question is the smallest mechanism that genuinely
works, not the most capable one.

## Decision
A single long-running `scheduler` process (`app/workers/scheduler.py`) invokes the
existing worker entry points on configurable intervals. It is deployed as a container
alongside the API, and in Compose it is its own service.

Rejected alternatives, and why:

- **A queue/worker framework (Celery, ARQ, Dramatiq).** New infrastructure, a new broker
  to operate, and a new failure mode, for two periodic jobs with no fan-out and no
  retries-with-backoff requirement. That is the premature architecture the guardrails
  forbid.
- **System cron in the API image.** Cron would need its own copy of the app, its
  dependencies and its configuration, and the image already has all three.
- **In-process background tasks inside the API.** A sweep that overruns would compete
  with request handling, and every API replica would run its own copy.

**The scheduler is not a singleton and must never be assumed to be one.** Both jobs are
idempotent and safe to run concurrently with themselves; correctness comes from the
database constraints the request path already relies on —
`UNIQUE(participant, challenge_day)` on `warning`, `UNIQUE(participant)` on `elimination`,
`uq_xp_transaction_idempotency`, the `expires_at`/`object_deleted_at` guards on media, and
`SELECT … FOR UPDATE SKIP LOCKED` on the retention batch. `tests/integration/
test_system_concurrency.py` runs four overlapping sweeps on independent connections and
asserts no duplicate warning, elimination, progress row or XP award.

Each challenge is swept in its own transaction, so one failure cannot roll back the
challenges already resolved, and a crash mid-sweep resumes on the next run. A failing job
logs and waits for its next tick rather than exiting: one broken sweep must not also stop
media retention, and a crash-looping container turns a recoverable error into an outage.

## Consequences
- Warnings and eliminations now occur on schedule whether or not anyone opens the app,
  which is what §20.5 always specified.
- Retention actually runs, so the storage-cost constraint is enforced rather than
  aspirational.
- The lazy sweep is deliberately **kept**. It costs nothing when the scheduler is healthy
  (the second pass is a read), and it means a scheduler outage degrades timeliness rather
  than correctness — anyone who opens the app still sees correctly resolved state.
- A platform with a native scheduler can run `python -m app.workers.deadline_sweep` /
  `media_cleanup` on its own cron and set `SCHEDULER_DISABLED_JOBS` to disable this
  process. The workers stay independently runnable specifically to keep that door open.
- Intervals are environment-configurable (`SCHEDULER_*`), so tuning needs no code change.
