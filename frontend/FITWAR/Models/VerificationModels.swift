import Foundation

/// Normalized evidence, the wire form of the §8 boundary.
///
/// Deliberately free of HealthKit vocabulary: units are explicit strings, instants are
/// UTC, and the value is a decimal string so no floating-point drift reaches the server.
/// A future Health Connect client fills in exactly this shape.
struct HealthEvidencePayload: Encodable, Sendable, Equatable {
    let metric: ActivityType
    /// Decimal string, not Double — the server stores `Numeric(12,2)` and JSON floats
    /// would round-trip imprecisely.
    let value: String
    let unit: String
    let periodStart: Date
    let periodEnd: Date
    let sourceName: String?
    let sourceBundleId: String?
    let wasUserEntered: Bool
}

struct SubmitVerificationRequest: Encodable, Sendable {
    let provider: HealthProviderKindDTO
    let evidence: HealthEvidencePayload
}

enum HealthProviderKindDTO: String, Codable, Sendable {
    case appleHealth = "apple_health"
    case healthConnect = "health_connect"
}

enum VerificationStatus: String, Decodable, Sendable, Equatable {
    case verified
    case pendingReview = "pending_review"
    case rejected
    case inconclusive
}

struct VerificationRecord: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let provider: String
    let metric: String
    @APIDecimal var value: Decimal
    @APIDecimal var target: Decimal
    let status: VerificationStatus
    /// Stable machine-readable explanation of a non-verified outcome. The client
    /// switches on this, never on `detail` copy.
    let reasonCode: String?
    let sourceTimestamp: Date
    let verifiedAt: Date?
}

/// The server's verdict. `dayStatus` is authoritative — the client renders it and never
/// computes completion itself (Architecture §1, tenet 1).
struct SubmitVerificationResponse: Decodable, Sendable, Equatable {
    let verification: VerificationRecord
    let challengeDay: Date
    let dayStatus: DailyProgressStatus
    let deadlineAt: Date
    /// True when this repeated an already-completed day; the same result comes back
    /// rather than a second one being recorded.
    let idempotentReplay: Bool
    /// What the day earned, when this submission actually completed it. Absent on a
    /// replay or a short attempt — nothing was awarded, and a zeroed struct would
    /// render as a real award of 0 XP.
    let resolution: DayResolution?
}

// MARK: - Health connections

enum HealthConnectionStatus: String, Decodable, Sendable, Equatable {
    case connected
    case revoked
}

struct HealthConnection: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let provider: HealthProviderKindDTO
    let status: HealthConnectionStatus
    /// The server's own observation of when evidence last arrived — not a client claim
    /// about permissions, which iOS won't reliably report anyway.
    let lastSyncedAt: Date?
    let connectedAt: Date
}

struct CreateHealthConnectionRequest: Encodable, Sendable {
    let provider: HealthProviderKindDTO
}
