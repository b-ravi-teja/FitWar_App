import Foundation
import Testing
@testable import FITWAR

@MainActor
struct SessionManagerTests {
    private func makeSUT() -> (SessionManager, MockAuthService, MockKeychainStore) {
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sut = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return (sut, authService, keychain)
    }

    @Test func loginSuccessTransitionsToAuthenticated() async throws {
        let (sut, authService, keychain) = makeSUT()
        let userId = UUID()
        authService.loginResult = .success(
            AuthenticatedSession(userId: userId, accessToken: "access", refreshToken: "refresh", expiresIn: 900)
        )

        try await sut.login(email: "ravi@example.com", password: "hunter2222")

        #expect(sut.state == .authenticated(userId: userId))
        #expect(keychain.saveCallCount == 1)
    }

    @Test func loginFailureReturnsToLoggedOut() async throws {
        let (sut, authService, _) = makeSUT()
        authService.loginResult = .failure(APIError.server(status: 401, code: "INVALID_CREDENTIALS", detail: "Incorrect email or password."))

        await #expect(throws: APIError.self) {
            try await sut.login(email: "ravi@example.com", password: "wrong")
        }
        #expect(sut.state == .loggedOut)
    }

    @Test func bootstrapWithNoStoredTokenGoesToLoggedOut() async {
        let (sut, _, _) = makeSUT()
        await sut.bootstrap()
        #expect(sut.state == .loggedOut)
    }

    @Test func bootstrapWithValidRefreshTokenResumesSession() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("stored-refresh", for: KeychainKey.refreshToken)
        let userId = UUID()
        let access = TestJWT.make(subject: userId)
        authService.refreshResult = .success(TokenResponseDTO(accessToken: access, refreshToken: "new-refresh", expiresIn: 900))

        await sut.bootstrap()

        #expect(sut.state == .authenticated(userId: userId))
    }

    @Test func bootstrapWithInvalidRefreshTokenGoesToLoggedOutAndClearsKeychain() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("stale-refresh", for: KeychainKey.refreshToken)
        authService.refreshResult = .failure(APIError.server(status: 401, code: "REFRESH_INVALID", detail: "expired"))

        await sut.bootstrap()

        #expect(sut.state == .loggedOut)
        #expect(keychain.deleteCallCount == 1)
    }

    @Test func logoutClearsSessionAndCallsBackend() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("refresh", for: KeychainKey.refreshToken)
        authService.loginResult = .success(AuthenticatedSession(userId: UUID(), accessToken: "a", refreshToken: "refresh", expiresIn: 900))
        try await sut.login(email: "x@example.com", password: "hunter2222")

        await sut.logout()

        #expect(sut.state == .loggedOut)
        #expect(authService.logoutCallCount == 1)
    }

    @Test func authorizedRequestRetriesOnceAfterRefreshingOn401() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("refresh", for: KeychainKey.refreshToken)
        let userId = UUID()
        authService.refreshResult = .success(TokenResponseDTO(accessToken: TestJWT.make(subject: userId), refreshToken: "new", expiresIn: 900))

        var callCount = 0
        let result = try await sut.authorizedRequest { () -> String in
            callCount += 1
            if callCount == 1 {
                throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
            }
            return "ok"
        }

        #expect(result == "ok")
        #expect(callCount == 2)
        #expect(sut.state == .authenticated(userId: userId))
    }

    @Test func authorizedRequestGoesToSessionExpiredWhenRefreshFails() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("refresh", for: KeychainKey.refreshToken)
        authService.refreshResult = .failure(APIError.server(status: 401, code: "REFRESH_INVALID", detail: "expired"))

        await #expect(throws: Error.self) {
            try await sut.authorizedRequest { () -> String in
                throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
            }
        }
        #expect(sut.state == .sessionExpired)
    }

    @Test func acknowledgeSessionExpiredReturnsToLoggedOut() async {
        let (sut, _, _) = makeSUT()
        sut.acknowledgeSessionExpired()
        #expect(sut.state == .loggedOut)
    }
}
