import Foundation

/// Mirrors `GET /api/v1/me`'s response exactly (API_SPEC.md). Only fields backed by
/// real persisted data in Phase 1/2 are here — no `level`/`current_streak`/etc., since
/// those require the XP/Streak/Challenge domains that don't exist yet (see the Phase 2
/// report's notes on `ProfileView`).
struct User: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let email: String
    let displayName: String
    let avatarMediaId: UUID?
    let xpTotal: Int
    let notificationPreferences: [String: Bool]?
}
