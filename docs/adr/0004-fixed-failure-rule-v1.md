# ADR 0004 — Fixed Failure-Rule Threshold, SURVIVAL-Mode Only

## Status
Accepted

## Context
Phase 0 designed `ChallengeRule` as a generic key/value extension point partly anticipating a configurable warning/elimination threshold. The design's "Set the rules" create-flow screen displays rule values as a read-only summary, not editable controls, leaving open whether V1 needed to support creator-configured thresholds. Separately, it was unclear whether the warning/elimination pipeline applied to all three game modes or only some — the design's own POINTS-mode copy ("everyone keeps playing") and the absence of any mid-battle elimination UI suggested otherwise.

## Decision
V1 uses a **fixed, non-configurable** failure rule: miss 1 day → `WARNING`, miss 2 **consecutive** days → `ELIMINATED`. "Consecutive" means a completed day resets `ChallengeParticipant.consecutive_misses` to 0 — a warning does not carry across an intervening success, matching the design's own copy ("Complete today's mission to reset. Nobody's out yet.").

This rule applies **only to `SURVIVAL`-mode challenges.** `POINTS` has no elimination. `1V1` battles resolve purely by final score at the end of their fixed duration, with no early-termination mechanic.

The threshold values are constants in `domain/challenges/failure_rule.py`. No `ChallengeRule` rows are written for this in V1.

## Consequences
- `ChallengeParticipant` gains one column (`consecutive_misses`) — a cached counter, same treatment as `current_streak`, reconstructable from `DailyChallengeProgress` history.
- `ChallengeRule` remains available, unused for this purpose in V1: making the threshold configurable later is "read from a `ChallengeRule` row instead of a constant" — a service-layer change, not a migration.
- The elimination service only ever runs for `SURVIVAL` challenges; `POINTS`/`1V1` challenge-close logic never calls it.
