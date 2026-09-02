import Foundation

protocol GameServiceProtocol: Sendable {
    func fetchLeaderboard(challengeId: UUID) async throws -> Leaderboard
    func fetchMyGameState(challengeId: UUID) async throws -> MyChallengeGameState
    func fetchXPSummary() async throws -> XPSummary
}

struct GameService: GameServiceProtocol {
    let client: APIClientProtocol

    func fetchLeaderboard(challengeId: UUID) async throws -> Leaderboard {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/leaderboard",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func fetchMyGameState(challengeId: UUID) async throws -> MyChallengeGameState {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/me",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func fetchXPSummary() async throws -> XPSummary {
        try await client.send(
            Endpoint(path: "/api/v1/me/xp", method: .get, requiresAuth: true)
        )
    }
}
