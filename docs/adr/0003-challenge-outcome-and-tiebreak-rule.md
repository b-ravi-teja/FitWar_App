# ADR 0003 — Challenge/Battle Outcome Model and Tie-Break Rule

## Status
Accepted

## Context
The Profile screen displays aggregate WINS/LOSSES/WIN-RATE stats and a per-challenge WON/LOST/OUT history, but the design never states the win condition per game mode, and no tie-break rule existed for equal final scores — leaving outcome computation ambiguous, which the Phase 0 architecture explicitly disallows for anything competitive.

## Decision

**Outcome per game mode**, persisted on `ChallengeParticipant.outcome`:

| Mode | WON | LOST | OUT | LEFT |
|---|---|---|---|---|
| SURVIVAL | Every participant who reaches challenge end without elimination (multiple winners possible) | — | Eliminated (2 consecutive misses) | Voluntarily left |
| POINTS | Single highest final score among finishers (tie-break below) | Every other finisher | — (no elimination in POINTS) | Voluntarily left |
| 1V1 (battle) | Higher final score (tie-break below); mirrored onto `BattleParticipant.status` | Lower final score | — | Declined/forfeited |

**Tie-break rule** (fixed, applies to POINTS ranking-at-close and 1V1 resolution alike, and to leaderboard rank ordering generally):
1. Highest final score wins.
2. If tied, earliest `completed_at` of the event that produced the final tally wins.
3. If still tied, longer `current_streak` at time of comparison wins.
4. If still tied, earlier `joined_at` wins.
5. If still tied (practically unreachable), lower `user_id` wins — a stable, arbitrary final fallback.

`outcome` is written once and is final: immediately for `OUT`/`LEFT` (elimination/leave are already terminal events elsewhere in the schema), at challenge-close time for `WON`/`LOST`.

## Consequences
- `ChallengeParticipant` gains one column (`outcome`, nullable enum) — no new table.
- The tie-break rule is implemented once, in `domain/challenges/`, and reused by both the leaderboard-rank comparator and the challenge-close/battle-resolution service — a single source of truth for "who's ahead" everywhere it matters.
- V1 never produces an unresolved draw in any competitive surface.
