import Foundation

/// API DTOs for the Challenges domain, mirroring `docs/API_SPEC.md` exactly.
///
/// Every status here is decided by the server. The client sends actions (create, join,
/// leave) and renders what comes back — it never computes a challenge status,
/// participant status, challenge day, or elimination itself.

enum ActivityType: String, Codable, Sendable, Equatable, CaseIterable {
    case steps
    case activeCalories = "active_calories"
    case distance
    case pushups

    var displayName: String {
        switch self {
        case .steps: "Steps"
        case .activeCalories: "Calories"
        case .distance: "Distance"
        case .pushups: "Push-ups"
        }
    }

    /// The unit sent with a new challenge — paired with the activity rather than
    /// free-typed, so a "steps" challenge can't be created measured in kilometres.
    var unit: String {
        switch self {
        case .steps: "steps"
        case .activeCalories: "kcal"
        case .distance: "km"
        case .pushups: "reps"
        }
    }

    var defaultTarget: Int {
        switch self {
        case .steps: 10_000
        case .activeCalories: 500
        case .distance: 5
        case .pushups: 50
        }
    }

    var symbolName: String {
        switch self {
        case .steps: "figure.walk"
        case .activeCalories: "flame"
        case .distance: "location"
        case .pushups: "figure.strengthtraining.traditional"
        }
    }
}

enum GameMode: String, Codable, Sendable, Equatable, CaseIterable {
    case survival
    case points

    var displayName: String { rawValue.uppercased() }

    var tag: String {
        switch self {
        case .survival: "MOST PLAYED"
        case .points: "FRIENDLY"
        }
    }

    var blurb: String {
        switch self {
        case .survival: "Hit the daily target or take a strike. Two strikes and you're out."
        case .points: "Everyone keeps playing. Highest total at the end takes the crown."
        }
    }
}

/// Modes the design shows as "SOON" chips. Not a `GameMode` case, because the API
/// rejects them — showing them as selectable would be a promise the backend breaks.
enum ComingSoonMode: String, CaseIterable, Sendable {
    case tournament = "TOURNAMENT"
    case teamBattle = "TEAM BATTLE"
    case bossBattle = "BOSS BATTLE"
}

enum VerificationMethod: String, Codable, Sendable, Equatable {
    case appleHealth = "apple_health"
    case manualProof = "manual_proof"

    var displayName: String {
        switch self {
        case .appleHealth: "HEALTH DATA"
        case .manualProof: "VIDEO PROOF"
        }
    }
}

enum ChallengeStatus: String, Decodable, Sendable, Equatable {
    case draft, active, completed, cancelled

    var displayName: String { rawValue.uppercased() }
}

enum ParticipantStatus: String, Decodable, Sendable, Equatable {
    case active, completed, left, eliminated

    var displayName: String { rawValue.uppercased() }
}

enum ParticipantOutcome: String, Decodable, Sendable, Equatable {
    case won, lost, out, left
}

enum DailyProgressStatus: String, Decodable, Sendable, Equatable {
    case pending, completed, missed, excused
}

/// A challenge card in the Challenges list.
struct ChallengeSummary: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let groupId: UUID
    let name: String
    let activityType: ActivityType
    let gameMode: GameMode
    let status: ChallengeStatus
    @APIDecimal var targetValue: Decimal
    let unit: String
    let dayIndex: Int
    let durationDays: Int
    let participantCount: Int
    let myStatus: ParticipantStatus?

    var metaLine: String {
        "\(gameMode.displayName) · DAY \(dayIndex)/\(durationDays) · \(participantCount) PLAYER\(participantCount == 1 ? "" : "S")"
    }

    var targetLabel: String {
        "\(FWNumber.compact(targetValue)) \(unit.uppercased())"
    }

    var remainingLabel: String {
        switch status {
        case .completed: return "FINISHED"
        case .cancelled: return "CANCELLED"
        case .draft: return "NOT STARTED"
        case .active:
            let remaining = max(0, durationDays - dayIndex)
            return remaining == 0 ? "FINAL DAY" : "\(remaining) DAYS LEFT"
        }
    }

    /// How far through the challenge's *schedule* this is — deliberately not a metric
    /// progress bar. There is no verified daily value to show until Phase 4, and a bar
    /// filled from nothing would read as real performance.
    var scheduleProgress: Double {
        guard durationDays > 0 else { return 0 }
        return min(1, max(0, Double(dayIndex) / Double(durationDays)))
    }
}

struct ChallengeParticipantSummary: Decodable, Identifiable, Sendable, Equatable {
    let userId: UUID
    let displayName: String
    let status: ParticipantStatus
    let outcome: ParticipantOutcome?
    @APIDecimal var currentScore: Decimal
    let currentStreak: Int
    let rank: Int
    let joinedAt: Date

    var id: UUID { userId }
}

struct ChallengeDetail: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let groupId: UUID
    let groupName: String
    let creatorId: UUID
    let name: String
    let activityType: ActivityType
    let gameMode: GameMode
    let verificationMethod: VerificationMethod
    let status: ChallengeStatus
    @APIDecimal var targetValue: Decimal
    let unit: String
    let timezone: String
    let startAt: Date
    let endAt: Date
    let dayIndex: Int
    let durationDays: Int
    let participantCount: Int
    let participantLimit: Int?
    let failureRule: String
    let myStatus: ParticipantStatus?
    let participants: [ChallengeParticipantSummary]

    var headerMeta: String {
        "DAY \(dayIndex) / \(durationDays) · \(failureRule)"
    }

    var modeMeta: String {
        "\(gameMode.displayName) · \(participantCount) PLAYER\(participantCount == 1 ? "" : "S")"
    }

    var targetLabel: String {
        "\(FWNumber.compact(targetValue)) \(unit.uppercased())"
    }

    var isJoinable: Bool {
        myStatus == nil && (status == .active || status == .draft)
    }

    var isLeavable: Bool {
        myStatus == .active && (status == .active || status == .draft)
    }
}

/// Today's (or a given day's) progress. There is deliberately no `currentValue` —
/// see the backend schema's note: a zero would render as "you've done nothing",
/// which is not what PENDING means.
struct DailyProgress: Decodable, Sendable, Equatable {
    let challengeDay: Date
    let dayIndex: Int
    let status: DailyProgressStatus
    @APIDecimal var target: Decimal
    let unit: String
    /// Both bounds of the challenge day in UTC, published by the server from the
    /// challenge's frozen timezone. The client must query health data over exactly this
    /// span rather than its own calendar day — a DST day isn't 24h, so deriving the
    /// start from `deadlineAt` would be wrong twice a year, and the challenge timezone
    /// is frequently not the device's at all.
    let windowStartAt: Date
    let deadlineAt: Date
    let completedAt: Date?
}

struct CreateChallengeRequest: Encodable, Sendable {
    let name: String
    let activityType: ActivityType
    let targetValue: String
    let unit: String
    let gameMode: GameMode
    let verificationMethod: VerificationMethod
    let durationDays: Int
    let participantLimit: Int?
}

/// Number formatting shared by every screen that shows a target ("10,000 STEPS").
enum FWNumber {
    private static let grouped: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter
    }()

    static func compact(_ value: Decimal) -> String {
        grouped.string(from: value as NSDecimalNumber) ?? "\(value)"
    }

    /// Unformatted decimal for the wire — `compact` inserts grouping separators, which
    /// the server would reject as a malformed number.
    static func plain(_ value: Decimal) -> String {
        NSDecimalNumber(decimal: value).stringValue
    }

    static func compact(_ value: Int) -> String {
        grouped.string(from: NSNumber(value: value)) ?? "\(value)"
    }
}
