import Foundation
@testable import FITWAR

/// Configurable stand-in for `AuthServiceProtocol` — every method's result is set by
/// the test before exercising a view model, so unit tests never touch the network
/// (this phase's §20: "Network requests must be mocked in unit tests").
final class MockAuthService: AuthServiceProtocol, @unchecked Sendable {
    var loginResult: Result<AuthenticatedSession, Error> = .failure(APIError.unknown("not configured"))
    var registerResult: Result<AuthenticatedSession, Error> = .failure(APIError.unknown("not configured"))
    var refreshResult: Result<TokenResponseDTO, Error> = .failure(APIError.unknown("not configured"))
    var logoutResult: Result<Void, Error> = .success(())
    var requestPasswordResetResult: Result<Void, Error> = .success(())
    var confirmPasswordResetResult: Result<Void, Error> = .success(())

    private(set) var loginCallCount = 0
    private(set) var refreshCallCount = 0
    private(set) var logoutCallCount = 0

    func login(email: String, password: String) async throws -> AuthenticatedSession {
        loginCallCount += 1
        return try loginResult.get()
    }

    func register(email: String, password: String, displayName: String) async throws -> AuthenticatedSession {
        try registerResult.get()
    }

    /// Tokens actually presented to `/auth/refresh`, in order. The refresh-coalescing
    /// tests assert on these: presenting the *same* token twice is what makes a real
    /// server revoke the whole family.
    private(set) var presentedRefreshTokens: [String] = []
    /// Seconds to stall inside refresh, so a test can hold one in flight while others
    /// pile up behind it.
    var refreshDelay: Duration = .zero

    func refresh(refreshToken: String) async throws -> TokenResponseDTO {
        refreshCallCount += 1
        presentedRefreshTokens.append(refreshToken)
        if refreshDelay != .zero {
            try? await Task.sleep(for: refreshDelay)
        }
        return try refreshResult.get()
    }

    func logout(refreshToken: String) async throws {
        logoutCallCount += 1
        try logoutResult.get()
    }

    func requestPasswordReset(email: String) async throws {
        try requestPasswordResetResult.get()
    }

    func confirmPasswordReset(token: String, newPassword: String) async throws {
        try confirmPasswordResetResult.get()
    }
}

final class MockUserService: UserServiceProtocol, @unchecked Sendable {
    var fetchResult: Result<User, Error> = .failure(APIError.unknown("not configured"))
    var updateResult: Result<User, Error> = .failure(APIError.unknown("not configured"))
    var onboardingResult: Result<User, Error>?
    private(set) var fetchCallCount = 0
    private(set) var updatedDisplayNames: [String] = []
    /// Every stage written to the server, in order. Onboarding tests assert on this:
    /// progress that is not persisted is progress the user loses when they quit.
    private(set) var recordedStages: [OnboardingStage] = []

    func fetchCurrentUser() async throws -> User {
        fetchCallCount += 1
        return try fetchResult.get()
    }

    func updateDisplayName(_ displayName: String) async throws -> User {
        updatedDisplayNames.append(displayName)
        return try updateResult.get()
    }

    func updateOnboardingStage(_ stage: OnboardingStage) async throws -> User {
        recordedStages.append(stage)
        return try (onboardingResult ?? updateResult).get()
    }
}

/// Builders for `User`, so a test states only the field it is about.
enum UserFixtures {
    static func user(
        id: UUID = UUID(),
        displayName: String = "Ravi",
        xpTotal: Int = 0,
        onboardingStage: OnboardingStage = .completed,
        onboardingCompletedAt: Date? = Date(timeIntervalSince1970: 1_760_000_000)
    ) -> User {
        User(
            id: id,
            email: "ravi@example.com",
            displayName: displayName,
            avatarMediaId: nil,
            xpTotal: xpTotal,
            notificationPreferences: nil,
            onboardingStage: onboardingStage,
            onboardingCompletedAt: onboardingStage == .completed ? onboardingCompletedAt : nil
        )
    }
}

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {
    var sendHandler: (Endpoint) throws -> Any = { _ in fatalError("sendHandler not configured") }
    var sendNoContentError: Error?
    private(set) var sentEndpoints: [Endpoint] = []

    func send<T>(_ endpoint: Endpoint) async throws -> T where T: Decodable {
        sentEndpoints.append(endpoint)
        guard let value = try sendHandler(endpoint) as? T else {
            fatalError("MockAPIClient.sendHandler returned the wrong type for \(T.self)")
        }
        return value
    }

    func sendNoContent(_ endpoint: Endpoint) async throws {
        sentEndpoints.append(endpoint)
        if let sendNoContentError { throw sendNoContentError }
    }
}
