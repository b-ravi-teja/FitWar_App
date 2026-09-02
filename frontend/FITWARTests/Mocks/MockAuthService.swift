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

    func refresh(refreshToken: String) async throws -> TokenResponseDTO {
        refreshCallCount += 1
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
    private(set) var fetchCallCount = 0

    func fetchCurrentUser() async throws -> User {
        fetchCallCount += 1
        return try fetchResult.get()
    }

    func updateDisplayName(_ displayName: String) async throws -> User {
        try updateResult.get()
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
