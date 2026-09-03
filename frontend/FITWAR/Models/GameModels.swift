import Foundation

/// Server-computed competitive state. Every value here is authoritative — the client
/// renders these numbers and derives none of them (Architecture §1, tenet 1).

struct DayResolution: Decodable, Sendable, Equatable {
    let xpAwarded: Int
    /// Broken into components so Mission Complete can show the breakdown the design
    /// specifies ("completion + streak bonus") without the client inferring either.
    let completionXP: Int
    let streakBonusXP: Int
    @APIDecimal var scoreDelta: Decimal
    let currentStreak: Int

    private enum CodingKeys: String, CodingKey {
        case xpAwarded, completionXP = "completionXp", streakBonusXP = "streakBonusXp"
        case scoreDelta, currentStreak
    }
}

struct LeaderboardEntry: Decodable, Identifiable, Sendable, Equatable {
    /// Assigned by the server at read time from the frozen tie-break; never computed here.
    let rank: Int
    let userId: UUID
    let displayName: String
    @APIDecimal var score: Decimal
    let currentStreak: Int
    let status: ParticipantStatus
    let outcome: ParticipantOutcome?
    let isMe: Bool

    var id: UUID { userId }
}

struct Leaderboard: Decodable, Sendable, Equatable {
    let challengeId: UUID
    let gameMode: String
    /// The challenge has closed — these standings are final and will not change.
    let isFinal: Bool
    let entries: [LeaderboardEntry]
}

struct ChallengeWarning: Decodable, Sendable, Equatable {
    let challengeDay: Date
    let reason: String
    let createdAt: Date
}

struct MyChallengeGameState: Decodable, Sendable, Equatable {
    let challengeId: UUID
    let rank: Int?
    @APIDecimal var score: Decimal
    let currentStreak: Int
    let longestStreak: Int
    let consecutiveMisses: Int
    let status: ParticipantStatus
    let outcome: ParticipantOutcome?
    let warnings: [ChallengeWarning]
    let eliminatedAt: Date?
}

/// Why XP was granted.
///
/// Decoding is deliberately forgiving. This is a plain `String`-backed enum on the wire,
/// and a strict one throws on any value it does not know — so when Phase 7 added
/// `battle_win` server-side, every user who won a battle got a *completely broken* XP
/// screen, because one unrecognised ledger row failed the whole response. An unknown
/// reason now renders as a neutral row instead, the same principle `RealtimeEvent.parse`
/// applies to socket events: a server that adds a value must never break an older client.
enum XPReason: String, Decodable, Sendable, Equatable {
    case dailyCompletion = "daily_completion"
    case streakBonus = "streak_bonus"
    case battleWin = "battle_win"
    /// Anything this client predates. Never sent by the server under this name.
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = XPReason(rawValue: raw) ?? .unknown
    }

    var displayName: String {
        switch self {
        case .dailyCompletion: "Mission complete"
        case .streakBonus: "Streak bonus"
        case .battleWin: "Battle win"
        case .unknown: "XP earned"
        }
    }
}

struct XPTransactionEntry: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let amount: Int
    let reason: XPReason
    let createdAt: Date
}

struct XPSummary: Decodable, Sendable, Equatable {
    let xpTotal: Int
    /// Server-computed. The client previously derived a provisional level from XP;
    /// Phase 5 makes that the server's job, so there is one authoritative answer.
    let level: Int
    let xpIntoLevel: Int
    let xpToNextLevel: Int
    let transactions: [XPTransactionEntry]

    /// Fraction of the current level completed — presentation only, derived from
    /// server-supplied numbers rather than recomputing the level itself.
    var levelProgress: Double {
        let span = xpIntoLevel + xpToNextLevel
        guard span > 0 else { return 0 }
        return Double(xpIntoLevel) / Double(span)
    }
}
