import Foundation

protocol ChallengesServiceProtocol: Sendable {
    func listMyChallenges(status: ChallengeStatus?) async throws -> [ChallengeSummary]
    func listGroupChallenges(groupId: UUID) async throws -> [ChallengeSummary]
    func fetchChallenge(id: UUID) async throws -> ChallengeDetail
    func createChallenge(
        groupId: UUID, request: CreateChallengeRequest
    ) async throws -> ChallengeDetail
    func joinChallenge(id: UUID) async throws -> ChallengeDetail
    func leaveChallenge(id: UUID) async throws
    func fetchTodayProgress(challengeId: UUID) async throws -> DailyProgress
}

struct ChallengesService: ChallengesServiceProtocol {
    let client: APIClientProtocol

    func listMyChallenges(status: ChallengeStatus?) async throws -> [ChallengeSummary] {
        var endpoint = Endpoint(path: "/api/v1/challenges", method: .get, requiresAuth: true)
        if let status {
            endpoint.query["status"] = status.rawValue
        }
        return try await client.send(endpoint)
    }

    func listGroupChallenges(groupId: UUID) async throws -> [ChallengeSummary] {
        try await client.send(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/challenges",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func fetchChallenge(id: UUID) async throws -> ChallengeDetail {
        try await client.send(
            Endpoint(path: "/api/v1/challenges/\(id.uuidString)", method: .get, requiresAuth: true)
        )
    }

    func createChallenge(
        groupId: UUID, request: CreateChallengeRequest
    ) async throws -> ChallengeDetail {
        try await client.send(
            Endpoint(
                path: "/api/v1/groups/\(groupId.uuidString)/challenges",
                method: .post,
                body: Endpoint.encodedBody(request),
                requiresAuth: true
            )
        )
    }

    func joinChallenge(id: UUID) async throws -> ChallengeDetail {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(id.uuidString)/join",
                method: .post,
                requiresAuth: true
            )
        )
    }

    func leaveChallenge(id: UUID) async throws {
        try await client.sendNoContent(
            Endpoint(
                path: "/api/v1/challenges/\(id.uuidString)/leave",
                method: .post,
                requiresAuth: true
            )
        )
    }

    func fetchTodayProgress(challengeId: UUID) async throws -> DailyProgress {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/progress/today",
                method: .get,
                requiresAuth: true
            )
        )
    }
}
