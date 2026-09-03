import Foundation

/// API DTOs for 1v1 battles, mirroring `docs/API_SPEC.md`.
///
/// Every competitive value here is decided by the server. There is deliberately no
/// initializer, computed property or helper below that derives a winner, a score, a
/// rank or an XP amount — the client renders the verdict it is given (Architecture §1,
/// tenet 1). The one thing this file computes is presentation: which of the two sides
/// is "me", and what copy a status maps to.

enum BattleStatus: String, Decodable, Sendable, Equatable {
    case pending, active, completed, cancelled

    var displayName: String { rawValue.uppercased() }
}

enum BattleSideStatus: String, Decodable, Sendable, Equatable {
    case invited, accepted, declined, active, won, lost
}

/// The frozen `WON | LOST | OUT | LEFT`. A battle only ever produces the first two.
enum BattleOutcome: String, Decodable, Sendable, Equatable {
    case won, lost, out, left
}

struct BattleSide: Decodable, Identifiable, Sendable, Equatable {
    let userId: UUID
    let displayName: String
    let status: BattleSideStatus
    /// Server-computed from verified evidence. Never accumulated locally from a socket.
    @APIDecimal var score: Decimal
    let daysCompleted: Int
    let isMe: Bool

    var id: UUID { userId }
}

struct Battle: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let groupId: UUID
    let status: BattleStatus
    let activityType: ActivityType
    @APIDecimal var targetValue: Decimal
    let unit: String
    let dayIndex: Int
    let durationDays: Int
    let timezone: String
    let startAt: Date
    let endAt: Date
    let completedAt: Date?
    /// Server-computed countdown. The battle day belongs to the battle's frozen
    /// timezone, which is frequently not the device's, so this is never derived here.
    let timeRemainingSeconds: Int
    let sides: [BattleSide]
    /// Absent until the battle is finalized — there is no provisional winner to show.
    let winnerUserId: UUID?
    let myOutcome: BattleOutcome?
    /// What the XP ledger actually paid for this win, read back from the ledger by the
    /// server. `nil` for the loser and while the battle is unfinished — a `0` would
    /// render as "you earned nothing", which is a different claim.
    let myXPAwarded: Int?

    private enum CodingKeys: String, CodingKey {
        case id, groupId, status, activityType, targetValue, unit, dayIndex, durationDays
        case timezone, startAt, endAt, completedAt, timeRemainingSeconds, sides
        case winnerUserId, myOutcome, myXPAwarded = "myXpAwarded"
    }

    var me: BattleSide? { sides.first(where: \.isMe) }
    var opponent: BattleSide? { sides.first(where: { !$0.isMe }) }

    /// True once the server has decided — the only condition under which Victory or
    /// Defeat may be shown.
    var isFinalized: Bool { status == .completed && myOutcome != nil }

    /// Fraction of the split "vs" bar the caller occupies. Presentation only: it is
    /// derived from two server-supplied scores and decides nothing.
    var myShareOfScore: Double {
        guard let me, let opponent else { return 0.5 }
        let total = me.score + opponent.score
        guard total > 0 else { return 0.5 }
        return NSDecimalNumber(decimal: me.score / total).doubleValue
    }
}

struct BattleRival: Decodable, Identifiable, Sendable, Equatable {
    let userId: UUID
    let displayName: String
    /// Head-to-head record, counted server-side from finalized battles.
    let winsAgainst: Int
    let lossesAgainst: Int
    /// Set when a battle with this rival is already pending or active, so the row
    /// offers "VIEW" instead of a "CHALLENGE" the server would refuse.
    let liveBattleId: UUID?

    var id: UUID { userId }

    var record: String { "\(winsAgainst)W – \(lossesAgainst)L" }
}

struct CreateBattleRequest: Encodable, Sendable {
    let opponentUserId: UUID
    let activityType: ActivityType
    /// Decimal string, as everywhere else — the server stores `NUMERIC(12,2)`.
    let targetValue: String?
    let durationDays: Int
    let groupId: UUID?
}

/// `POST /battles/{id}/verify` — the verification verdict plus the battle it changed.
struct SubmitBattleEvidenceResponse: Decodable, Sendable, Equatable {
    let verification: SubmitVerificationResponse
    let battle: Battle
}
