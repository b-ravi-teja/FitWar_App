import Foundation

protocol VerificationServiceProtocol: Sendable {
    func submitVerification(
        challengeId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitVerificationResponse
    func listHealthConnections() async throws -> [HealthConnection]
    func connectHealthProvider(_ provider: HealthProviderKindDTO) async throws -> HealthConnection
    func disconnectHealthProvider(id: UUID) async throws
}

struct VerificationService: VerificationServiceProtocol {
    let client: APIClientProtocol

    func submitVerification(
        challengeId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitVerificationResponse {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/verify",
                method: .post,
                body: Endpoint.encodedBody(request),
                requiresAuth: true
            )
        )
    }

    func listHealthConnections() async throws -> [HealthConnection] {
        try await client.send(
            Endpoint(path: "/api/v1/me/health-connections", method: .get, requiresAuth: true)
        )
    }

    func connectHealthProvider(_ provider: HealthProviderKindDTO) async throws -> HealthConnection {
        try await client.send(
            Endpoint(
                path: "/api/v1/me/health-connections",
                method: .post,
                body: Endpoint.encodedBody(CreateHealthConnectionRequest(provider: provider)),
                requiresAuth: true
            )
        )
    }

    func disconnectHealthProvider(id: UUID) async throws {
        try await client.sendNoContent(
            Endpoint(
                path: "/api/v1/me/health-connections/\(id.uuidString)",
                method: .delete,
                requiresAuth: true
            )
        )
    }
}
