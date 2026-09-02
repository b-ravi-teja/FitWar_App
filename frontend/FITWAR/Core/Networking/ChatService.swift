import Foundation

protocol ChatServiceProtocol: Sendable {
    func fetchMessages(
        groupId: UUID, before: Date?, beforeId: UUID?, limit: Int
    ) async throws -> ChatPage
    func postMessage(groupId: UUID, content: String) async throws -> ChatMessage
    func react(groupId: UUID, messageId: UUID, emoji: String, add: Bool) async throws
}

struct ChatService: ChatServiceProtocol {
    let client: APIClientProtocol

    func fetchMessages(
        groupId: UUID, before: Date?, beforeId: UUID?, limit: Int
    ) async throws -> ChatPage {
        var endpoint = Endpoint(
            path: "/api/v1/groups/\(groupId.uuidString)/messages",
            method: .get,
            requiresAuth: true
        )
        endpoint.query["limit"] = String(limit)
        if let before {
            // Both halves of the cursor: timestamps tie, ids don't.
            endpoint.query["before"] = FITWARDateParsing.fractional.string(from: before)
            if let beforeId { endpoint.query["before_id"] = beforeId.uuidString }
        }
        return try await client.send(endpoint)
    }

    func postMessage(groupId: UUID, content: String) async throws -> ChatMessage {
        struct Body: Encodable { let content: String }
        return try await client.send(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/messages",
                method: .post,
                body: Endpoint.encodedBody(Body(content: content)),
                requiresAuth: true
            )
        )
    }

    func react(groupId: UUID, messageId: UUID, emoji: String, add: Bool) async throws {
        struct Body: Encodable { let emoji: String; let add: Bool }
        try await client.sendNoContent(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/messages/\(messageId.uuidString)/reactions",
                method: .post,
                body: Endpoint.encodedBody(Body(emoji: emoji, add: add)),
                requiresAuth: true
            )
        )
    }
}
