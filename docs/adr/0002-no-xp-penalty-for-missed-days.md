# ADR 0002 — No XP Penalty for Missed Days

## Status
Accepted

## Context
The design's mock XP-history data included one entry reading "Missed mission … −40," suggesting a missed day might dock XP. This was demo filler, not a stated product rule, and was flagged as needing a decision before the XP domain logic could be implemented (the exact penalty amount, scaling, and trigger condition were all unspecified).

## Decision
V1 applies **no XP penalty for missing a day**. A missed day affects only:
- `DailyChallengeProgress.status` (→ `missed`)
- `ChallengeParticipant.current_streak` (resets) and `.consecutive_misses` (increments)
- The warning/elimination pipeline (ADR 0004)

No `XPTransaction` row is ever written for a miss.

## Consequences
- The XP ledger (`XPTransaction`) stays strictly additive in V1 — every row has a non-negative `amount`. (The schema itself does not enforce non-negativity, since a future decision may introduce penalties or corrections; V1's *service layer* simply never writes one.)
- The XP History screen never shows a negative entry in V1.
- Rationale for revisiting later: once player behavior is validated, a penalty could be reintroduced without a schema change — it's a service-layer rule, not a structural one.
