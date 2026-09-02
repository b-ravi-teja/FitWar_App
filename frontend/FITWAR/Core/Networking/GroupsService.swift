import Foundation

/// Protocol-first so ViewModel tests mock this instead of standing up a live server
/// (Architecture §14: "no live network in unit tests").
protocol GroupsServiceProtocol: Sendable {
    func listGroups() async throws -> [GroupSummary]
    func createGroup(name: String, timezone: String) async throws -> GroupDetail
    func joinGroup(code: String) async throws -> GroupDetail
    func fetchGroup(id: UUID) async throws -> GroupDetail
    func fetchMembers(groupId: UUID) async throws -> [GroupMemberSummary]
    func fetchActivity(groupId: UUID) async throws -> [GroupActivityEntry]
    func leaveGroup(id: UUID) async throws
}

struct GroupsService: GroupsServiceProtocol {
    let client: APIClientProtocol

    func listGroups() async throws -> [GroupSummary] {
        try await client.send(Endpoint(path: "/api/v1/groups", method: .get, requiresAuth: true))
    }

    func createGroup(name: String, timezone: String) async throws -> GroupDetail {
        let body = CreateGroupRequest(name: name, timezone: timezone)
        return try await client.send(
            Endpoint(
                path: "/api/v1/groups",
                method: .post,
                body: Endpoint.encodedBody(body),
                requiresAuth: true
            )
        )
    }

    func joinGroup(code: String) async throws -> GroupDetail {
        let body = JoinGroupRequest(joinCode: code)
        return try await client.send(
            Endpoint(
                path: "/api/v1/groups/join",
                method: .post,
                body: Endpoint.encodedBody(body),
                requiresAuth: true
            )
        )
    }

    func fetchGroup(id: UUID) async throws -> GroupDetail {
        try await client.send(
            Endpoint(path: "/api/v1/groups/\(id.uuidString)", method: .get, requiresAuth: true)
        )
    }

    func fetchMembers(groupId: UUID) async throws -> [GroupMemberSummary] {
        try await client.send(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/members",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func fetchActivity(groupId: UUID) async throws -> [GroupActivityEntry] {
        try await client.send(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/activity",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func leaveGroup(id: UUID) async throws {
        try await client.sendNoContent(
            Endpoint(
                path: "/api/v1/groups/\(id.uuidString)/leave",
                method: .post,
                requiresAuth: true
            )
        )
    }
}
