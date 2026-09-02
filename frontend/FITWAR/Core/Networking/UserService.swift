import Foundation

protocol UserServiceProtocol: Sendable {
    func fetchCurrentUser() async throws -> User
    func updateDisplayName(_ displayName: String) async throws -> User
}

private struct UpdateProfileRequestDTO: Encodable {
    let displayName: String
}

struct UserService: UserServiceProtocol {
    let client: APIClientProtocol

    func fetchCurrentUser() async throws -> User {
        try await client.send(Endpoint(path: "/api/v1/me", method: .get, requiresAuth: true))
    }

    func updateDisplayName(_ displayName: String) async throws -> User {
        let body = UpdateProfileRequestDTO(displayName: displayName)
        return try await client.send(
            Endpoint(path: "/api/v1/me", method: .patch, body: Endpoint.encodedBody(body), requiresAuth: true)
        )
    }
}
