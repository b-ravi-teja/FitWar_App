import Foundation

/// Media, proof-review and chat models. Every decision here is the server's — the client
/// uploads bytes, submits evidence, and renders verdicts.

enum MediaStatus: String, Decodable, Sendable, Equatable {
    case pending, processed, failed
    /// The object was deleted by retention. The record survives; the video does not.
    case expired
}

struct PresignedUpload: Decodable, Sendable, Equatable {
    let mediaId: UUID
    let url: String
    /// Signed POST-policy fields, sent verbatim. The app never holds bucket credentials.
    let fields: [String: String]
    let expiresInSeconds: Int
    let maxBytes: Int
}

struct MediaAsset: Decodable, Sendable, Equatable {
    let id: UUID
    let status: MediaStatus
    let contentType: String
    let sizeBytes: Int?
    /// Nil once retention has deleted the object — the UI says "no longer available"
    /// rather than showing a player that will never load.
    let playbackURL: String?
    let expiresAt: Date?
    let objectDeletedAt: Date?

    var isAvailable: Bool { playbackURL != nil && objectDeletedAt == nil }

    private enum CodingKeys: String, CodingKey {
        case id, status, contentType, sizeBytes
        case playbackURL = "playbackUrl"
        case expiresAt, objectDeletedAt
    }
}

struct PendingProof: Decodable, Identifiable, Sendable, Equatable {
    let verificationRecordId: UUID
    let participantUserId: UUID
    let participantDisplayName: String
    let challengeDay: Date?
    @APIDecimal var claimedValue: Decimal
    @APIDecimal var target: Decimal
    let submittedAt: Date
    let mediaId: UUID?
    let mediaAvailable: Bool

    var id: UUID { verificationRecordId }
}

struct ReviewProofResult: Decodable, Sendable, Equatable {
    let verificationRecordId: UUID
    let status: VerificationStatus
    let reviewedAt: Date?
    /// The proof was already resolved — the existing decision is returned unchanged.
    let alreadyResolved: Bool
    let xpAwarded: Int?
    let currentStreak: Int?
}

// MARK: - Chat

enum ChatMessageType: String, Decodable, Sendable, Equatable {
    case text
    /// Emitted by the game system; chat only presents it.
    case system
}

struct ReactionSummary: Decodable, Sendable, Equatable, Identifiable {
    let emoji: String
    let count: Int
    let reactedByMe: Bool

    var id: String { emoji }
}

struct ChatMessage: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let groupId: UUID
    let senderId: UUID?
    let senderDisplayName: String?
    let content: String
    let messageType: ChatMessageType
    let createdAt: Date
    let reactions: [ReactionSummary]
}

struct ChatPage: Decodable, Sendable, Equatable {
    let items: [ChatMessage]
    /// Cursor pair for the next page — both parts are needed because timestamps tie.
    let nextCursor: Date?
    let nextCursorId: UUID?
}

/// The fixed V1 reaction set, mirroring the server's allow-list.
enum FWReaction {
    static let all = ["🔥", "💪", "👏", "😤", "💀"]
}
