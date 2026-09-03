import Foundation
@testable import FITWAR

final class MockMediaService: MediaServiceProtocol, @unchecked Sendable {
    var prepareResult: Result<PresignedUpload, Error> = .success(
        PresignedUpload(
            mediaId: UUID(), url: "https://storage.example/bucket",
            fields: ["key": "k"], expiresInSeconds: 900, maxBytes: 262_144_000
        )
    )
    var uploadError: Error?
    var completeResult: Result<MediaAsset, Error> = .success(MediaFixtures.asset())
    var pendingResult: Result<[PendingProof], Error> = .success([])
    var proofMediaResult: Result<MediaAsset, Error> = .success(MediaFixtures.asset())
    var reviewResult: Result<ReviewProofResult, Error> = .failure(APIError.unknown("not configured"))

    private(set) var uploadedBytes: Int?
    private(set) var completedIds: [UUID] = []
    private(set) var reviewCalls: [(UUID, Bool)] = []

    func prepareUpload(contentType: String) async throws -> PresignedUpload {
        try prepareResult.get()
    }

    func uploadData(_ data: Data, to grant: PresignedUpload, contentType: String) async throws {
        if let uploadError { throw uploadError }
        uploadedBytes = data.count
    }

    func completeUpload(mediaId: UUID) async throws -> MediaAsset {
        completedIds.append(mediaId)
        return try completeResult.get()
    }

    func fetchPendingProofs(challengeId: UUID) async throws -> [PendingProof] {
        try pendingResult.get()
    }

    func fetchProofMedia(challengeId: UUID, recordId: UUID) async throws -> MediaAsset {
        try proofMediaResult.get()
    }

    func reviewProof(
        challengeId: UUID, recordId: UUID, approve: Bool, note: String?
    ) async throws -> ReviewProofResult {
        reviewCalls.append((recordId, approve))
        return try reviewResult.get()
    }
}

final class MockChatService: ChatServiceProtocol, @unchecked Sendable {
    var pageResult: Result<ChatPage, Error> = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))
    var pages: [ChatPage] = []
    var postResult: Result<ChatMessage, Error> = .failure(APIError.unknown("not configured"))
    var reactError: Error?

    private(set) var fetchCount = 0
    private(set) var requestedCursors: [(Date?, UUID?)] = []
    private(set) var postedContents: [String] = []
    private(set) var reactions: [(UUID, String, Bool)] = []

    func fetchMessages(
        groupId: UUID, before: Date?, beforeId: UUID?, limit: Int
    ) async throws -> ChatPage {
        requestedCursors.append((before, beforeId))
        defer { fetchCount += 1 }
        if !pages.isEmpty {
            return pages[min(fetchCount, pages.count - 1)]
        }
        return try pageResult.get()
    }

    func postMessage(groupId: UUID, content: String) async throws -> ChatMessage {
        postedContents.append(content)
        return try postResult.get()
    }

    func react(groupId: UUID, messageId: UUID, emoji: String, add: Bool) async throws {
        if let reactError { throw reactError }
        reactions.append((messageId, emoji, add))
    }
}

final class MockRealtimeClient: RealtimeClientProtocol, @unchecked Sendable {
    var eventsToEmit: [RealtimeEvent] = []
    private(set) var connectCount = 0
    private(set) var disconnectCount = 0

    private(set) var battleConnectCount = 0

    func events(groupId: UUID, token: String) -> AsyncStream<RealtimeEvent> {
        connectCount += 1
        return stream()
    }

    func events(battleId: UUID, token: String) -> AsyncStream<RealtimeEvent> {
        battleConnectCount += 1
        return stream()
    }

    private func stream() -> AsyncStream<RealtimeEvent> {
        let queued = eventsToEmit
        return AsyncStream { continuation in
            for event in queued { continuation.yield(event) }
            // Finishing models the socket dropping — the consumer falls back to REST.
            continuation.finish()
        }
    }

    func disconnect() { disconnectCount += 1 }
}

enum MediaFixtures {
    static func asset(
        status: MediaStatus = .processed,
        playbackURL: String? = "https://storage.example/signed",
        deletedAt: Date? = nil
    ) -> MediaAsset {
        MediaAsset(
            id: UUID(),
            status: status,
            contentType: "video/mp4",
            sizeBytes: 2048,
            playbackURL: playbackURL,
            expiresAt: nil,
            objectDeletedAt: deletedAt
        )
    }

    static func pendingProof(name: String = "Athlete", available: Bool = true) -> PendingProof {
        PendingProof(
            verificationRecordId: UUID(),
            participantUserId: UUID(),
            participantDisplayName: name,
            challengeDay: Date(timeIntervalSince1970: 1_760_000_000),
            claimedValue: 60,
            target: 50,
            submittedAt: Date(timeIntervalSince1970: 1_760_000_000),
            mediaId: UUID(),
            mediaAvailable: available
        )
    }

    static func message(
        content: String = "hello",
        type: ChatMessageType = .text,
        reactions: [ReactionSummary] = []
    ) -> ChatMessage {
        ChatMessage(
            id: UUID(),
            groupId: UUID(),
            senderId: UUID(),
            senderDisplayName: "Sender",
            content: content,
            messageType: type,
            createdAt: Date(timeIntervalSince1970: 1_760_000_000),
            reactions: reactions
        )
    }
}
