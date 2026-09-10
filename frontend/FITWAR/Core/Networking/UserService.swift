import Foundation

protocol UserServiceProtocol: Sendable {
    func fetchCurrentUser() async throws -> User
    func updateDisplayName(_ displayName: String) async throws -> User
    /// Record onboarding progress server-side after each step, so a user who quits
    /// mid-flow resumes where they stopped rather than starting over.
    func updateOnboardingStage(_ stage: OnboardingStage) async throws -> User
}

private struct UpdateProfileRequestDTO: Encodable {
    var displayName: String? = nil
    var onboardingStage: OnboardingStage? = nil
}

struct UserService: UserServiceProtocol {
    let client: APIClientProtocol

    func fetchCurrentUser() async throws -> User {
        try await client.send(Endpoint(path: "/api/v1/me", method: .get, requiresAuth: true))
    }

    func updateDisplayName(_ displayName: String) async throws -> User {
        try await patch(UpdateProfileRequestDTO(displayName: displayName))
    }

    func updateOnboardingStage(_ stage: OnboardingStage) async throws -> User {
        try await patch(UpdateProfileRequestDTO(onboardingStage: stage))
    }

    private func patch(_ body: UpdateProfileRequestDTO) async throws -> User {
        try await client.send(
            Endpoint(
                path: "/api/v1/me", method: .patch,
                body: Endpoint.encodedBody(body), requiresAuth: true
            )
        )
    }
}
