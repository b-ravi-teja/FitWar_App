import Foundation

/// How far first-run onboarding has got, as the **server** records it.
///
/// Deliberately server-backed rather than a device flag: a device flag is lost on
/// reinstall, absent on a second device, and easy to clear by accident on logout — all
/// of which would drag a returning user back through onboarding. The client asks where
/// it left off instead of remembering.
enum OnboardingStage: String, Codable, Sendable, Equatable, CaseIterable {
    case discipline
    case health
    case profile
    case completed

    /// An unrecognised value from a newer server decodes as `completed`.
    ///
    /// The failure modes are asymmetric: guessing "completed" for a stage this build
    /// doesn't understand sends the user to Home, which is recoverable. Guessing an
    /// onboarding step would trap them in a flow the app cannot finish.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = OnboardingStage(rawValue: raw) ?? .completed
    }

    var isComplete: Bool { self == .completed }
}

/// Mirrors `GET /api/v1/me`'s response exactly (API_SPEC.md). Only fields backed by
/// real persisted data are here — no `level`/`current_streak`/etc., which are served by
/// `GET /me/xp` and the challenge endpoints instead.
struct User: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let email: String
    let displayName: String
    let avatarMediaId: UUID?
    let xpTotal: Int
    let notificationPreferences: [String: Bool]?
    let onboardingStage: OnboardingStage
    let onboardingCompletedAt: Date?
}
