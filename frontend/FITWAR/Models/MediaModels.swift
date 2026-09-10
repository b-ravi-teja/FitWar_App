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
    /// `"POST"` (multipart form carrying `fields`) or `"PUT"` (raw body plus `headers`).
    /// Which one arrives depends on the deployed storage backend — Cloudflare R2 has no
    /// S3 PostObject, so an R2 deployment issues PUT grants. Defaulted so a response
    /// from a server predating the field still decodes.
    let method: String
    /// Headers to apply verbatim to a PUT grant. Empty for POST.
    let headers: [String: String]

    private enum CodingKeys: String, CodingKey {
        case mediaId, url, fields, expiresInSeconds, maxBytes, method, headers
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mediaId = try c.decode(UUID.self, forKey: .mediaId)
        url = try c.decode(String.self, forKey: .url)
        fields = try c.decodeIfPresent([String: String].self, forKey: .fields) ?? [:]
        expiresInSeconds = try c.decode(Int.self, forKey: .expiresInSeconds)
        maxBytes = try c.decode(Int.self, forKey: .maxBytes)
        method = (try c.decodeIfPresent(String.self, forKey: .method) ?? "POST").uppercased()
        headers = try c.decodeIfPresent([String: String].self, forKey: .headers) ?? [:]
    }

    /// Test/preview seam — the decoder above is the only path used in the app.
    init(
        mediaId: UUID, url: String, fields: [String: String], expiresInSeconds: Int,
        maxBytes: Int, method: String = "POST", headers: [String: String] = [:]
    ) {
        self.mediaId = mediaId
        self.url = url
        self.fields = fields
        self.expiresInSeconds = expiresInSeconds
        self.maxBytes = maxBytes
        self.method = method.uppercased()
        self.headers = headers
    }
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
