import Foundation

/// API DTOs for the Groups domain — each one mirrors a backend response shape exactly
/// (`docs/API_SPEC.md`). Views never reshape these into ad-hoc structs; where a screen
/// needs derived text it computes it from these, so there's one model per payload.

enum GroupRole: String, Decodable, Sendable, Equatable {
    case owner, admin, member

    var label: String { rawValue.uppercased() }
    var isAdmin: Bool { self == .owner || self == .admin }
}

enum GroupMemberStatus: String, Decodable, Sendable, Equatable {
    case active, left, removed
}

/// A row in the Groups List (`GET /api/v1/groups`).
struct GroupSummary: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let name: String
    let timezone: String
    let memberCount: Int
    let activeChallengeCount: Int

    /// The meta line under the group name, matching the design's
    /// "8 MEMBERS · 3 ACTIVE CHALLENGES".
    var metaLine: String {
        let members = "\(memberCount) MEMBER\(memberCount == 1 ? "" : "S")"
        let challenges = "\(activeChallengeCount) ACTIVE CHALLENGE\(activeChallengeCount == 1 ? "" : "S")"
        return "\(members) · \(challenges)"
    }
}

/// Full group detail (`GET /api/v1/groups/{id}`).
struct GroupDetail: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let name: String
    let timezone: String
    let privacy: String
    let ownerId: UUID
    let memberCount: Int
    let activeChallengeCount: Int
    let createdAt: Date
    let joinCode: String
    let myRole: GroupRole

    var metaLine: String {
        let members = "\(memberCount) MEMBER\(memberCount == 1 ? "" : "S")"
        let challenges = "\(activeChallengeCount) ACTIVE CHALLENGE\(activeChallengeCount == 1 ? "" : "S")"
        return "\(members) · \(challenges)"
    }
}

/// A Roster row (`GET /api/v1/groups/{id}/members`).
///
/// No streak or warning count: those need the XP/Streak and Warning domains, which
/// don't exist yet. The design's roster sub-label shows challenge participation
/// instead of a fabricated streak.
struct GroupMemberSummary: Decodable, Identifiable, Sendable, Equatable {
    let userId: UUID
    let displayName: String
    let role: GroupRole
    let status: GroupMemberStatus
    let joinedAt: Date
    let activeChallengeCount: Int

    var id: UUID { userId }

    var stateLabel: String {
        if activeChallengeCount == 0 { return "NO ACTIVE CHALLENGES" }
        return "IN \(activeChallengeCount) CHALLENGE\(activeChallengeCount == 1 ? "" : "S")"
    }
}

/// A Feed row (`GET /api/v1/groups/{id}/activity`).
struct GroupActivityEntry: Decodable, Identifiable, Sendable, Equatable {
    let kind: String
    let actorDisplayName: String
    let text: String
    let occurredAt: Date

    var id: String { "\(kind)-\(actorDisplayName)-\(occurredAt.timeIntervalSince1970)" }
}

struct CreateGroupRequest: Encodable, Sendable {
    let name: String
    let timezone: String
}

struct UpdateGroupRequest: Encodable, Sendable {
    var name: String?
    var timezone: String?
}

struct JoinGroupRequest: Encodable, Sendable {
    let joinCode: String
}
