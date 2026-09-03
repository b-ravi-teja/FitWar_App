import Foundation

protocol BattlesServiceProtocol: Sendable {
    func fetchBattles(status: BattleStatus?) async throws -> [Battle]
    func fetchBattle(id: UUID) async throws -> Battle
    func fetchRivals(groupId: UUID) async throws -> [BattleRival]
    func createBattle(_ request: CreateBattleRequest) async throws -> Battle
    func accept(battleId: UUID) async throws -> Battle
    func decline(battleId: UUID) async throws -> Battle
    func submitEvidence(
        battleId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitBattleEvidenceResponse
}

struct BattlesService: BattlesServiceProtocol {
    let client: APIClientProtocol

    func fetchBattles(status: BattleStatus?) async throws -> [Battle] {
        var endpoint = Endpoint(path: "/api/v1/battles", method: .get, requiresAuth: true)
        if let status { endpoint.query["status"] = status.rawValue }
        return try await client.send(endpoint)
    }

    func fetchBattle(id: UUID) async throws -> Battle {
        try await client.send(
            Endpoint(path: "/api/v1/battles/\(id.uuidString)", method: .get, requiresAuth: true)
        )
    }

    func fetchRivals(groupId: UUID) async throws -> [BattleRival] {
        var endpoint = Endpoint(path: "/api/v1/battles/rivals", method: .get, requiresAuth: true)
        endpoint.query["group_id"] = groupId.uuidString
        return try await client.send(endpoint)
    }

    func createBattle(_ request: CreateBattleRequest) async throws -> Battle {
        try await client.send(
            Endpoint(
                path: "/api/v1/battles",
                method: .post,
                body: Endpoint.encodedBody(request),
                requiresAuth: true
            )
        )
    }

    func accept(battleId: UUID) async throws -> Battle {
        try await client.send(
            Endpoint(
                path: "/api/v1/battles/\(battleId.uuidString)/accept",
                method: .post,
                requiresAuth: true
            )
        )
    }

    func decline(battleId: UUID) async throws -> Battle {
        try await client.send(
            Endpoint(
                path: "/api/v1/battles/\(battleId.uuidString)/decline",
                method: .post,
                requiresAuth: true
            )
        )
    }

    func submitEvidence(
        battleId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitBattleEvidenceResponse {
        try await client.send(
            Endpoint(
                path: "/api/v1/battles/\(battleId.uuidString)/verify",
                method: .post,
                body: Endpoint.encodedBody(request),
                requiresAuth: true
            )
        )
    }
}
