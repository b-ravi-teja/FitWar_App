# ADR 0006 — No Dedicated Notification Inbox Screen in V1

## Status
Accepted

## Context
The design has no notification list/inbox screen. Warnings and eliminations present as full-screen interstitials; lighter social events appear as passive system messages in group chat. Phase 0's backend already includes a `Notification` entity and push-worker design. It was unclear whether V1 iOS still needed a dedicated inbox screen to fully meet the "notifications are a product requirement" goal.

## Decision
V1 iOS ships **no dedicated notification inbox screen**. Delivery is: APNs push (backgrounded/killed app) + the existing full-screen interstitials (warning/elimination) + group chat system messages + a lightweight unread-count badge on the nav.

The `Notification` entity, its persistence, and its API (`GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`) are all still built exactly as Phase 0 specified — only the standalone list *screen* is deferred.

## Consequences
- A future release can add the inbox screen with zero backend work — it's a pure frontend addition consuming an API that already exists and is already being written to.
- `GET /notifications/unread-count` is added (not in the original Phase 0 sketch) specifically to back the badge without requiring the client to paginate the full list just to get a count.
