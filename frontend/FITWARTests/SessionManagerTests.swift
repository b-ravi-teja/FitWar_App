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

// MARK: - Phase 8: concurrent refresh must not rotate twice

@MainActor
struct SessionManagerRefreshCoalescingTests {
    private func makeSUT() -> (SessionManager, MockAuthService, MockKeychainStore) {
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sut = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return (sut, authService, keychain)
    }

    private func seed(_ keychain: MockKeychainStore, _ authService: MockAuthService) throws {
        try keychain.save("stored-refresh", for: KeychainKey.refreshToken)
        authService.refreshResult = .success(
            TokenResponseDTO(
                accessToken: TestJWT.make(subject: UUID()),
                refreshToken: "rotated-refresh",
                expiresIn: 900
            )
        )
    }

    @Test func concurrentUnauthorizedCallsTriggerExactlyOneRotation() async throws {
        /// The regression this locks down: refresh tokens rotate, and the server treats a
        /// second presentation of an already-rotated token as theft — it revokes the
        /// whole family. Two screens hitting 401 at once used to each present the same
        /// stored token, so the user was silently logged out for doing nothing wrong.
        let (sut, authService, keychain) = makeSUT()
        try seed(keychain, authService)
        authService.refreshDelay = .milliseconds(50)

        var attempts = 0
        let operation: @Sendable () async throws -> String = {
            await MainActor.run { attempts += 1 }
            if await MainActor.run(body: { attempts }) <= 4 {
                throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
            }
            return "ok"
        }

        async let a = sut.authorizedRequest { try await operation() }
        async let b = sut.authorizedRequest { try await operation() }
        async let c = sut.authorizedRequest { try await operation() }
        async let d = sut.authorizedRequest { try await operation() }
        _ = try? await [a, b, c, d]

        #expect(authService.refreshCallCount == 1)
    }

    @Test func aRotatedTokenIsNeverPresentedTwice() async throws {
        /// The precise server-side trigger: the same refresh token reaching
        /// `/auth/refresh` more than once.
        let (sut, authService, keychain) = makeSUT()
        try seed(keychain, authService)
        authService.refreshDelay = .milliseconds(40)

        let failOnce: @Sendable () async throws -> String = {
            throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
        }
        async let a: () = { _ = try? await sut.authorizedRequest { try await failOnce() } }()
        async let b: () = { _ = try? await sut.authorizedRequest { try await failOnce() } }()
        async let c: () = { _ = try? await sut.authorizedRequest { try await failOnce() } }()
        _ = await [a, b, c]

        let presented = authService.presentedRefreshTokens
        #expect(presented.count == Set(presented).count, "a token was presented twice: \(presented)")
    }

    @Test func aLaterRequestCanStillRefreshAfterTheFirstRotationFinished() async throws {
        /// Coalescing must not latch: once the in-flight refresh completes, a genuinely
        /// later 401 has to be able to rotate again.
        let (sut, authService, keychain) = makeSUT()
        try seed(keychain, authService)

        let alwaysUnauthorized: @Sendable () async throws -> String = {
            throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
        }
        _ = try? await sut.authorizedRequest { try await alwaysUnauthorized() }
        try keychain.save("stored-refresh-2", for: KeychainKey.refreshToken)
        _ = try? await sut.authorizedRequest { try await alwaysUnauthorized() }

        #expect(authService.refreshCallCount == 2)
    }

    @Test func aSuccessfulRefreshLetsTheOriginalCallSucceed() async throws {
        let (sut, authService, keychain) = makeSUT()
        try seed(keychain, authService)

        var calls = 0
        let value = try await sut.authorizedRequest { () async throws -> String in
            calls += 1
            if calls == 1 {
                throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
            }
            return "recovered"
        }

        #expect(value == "recovered")
        #expect(authService.refreshCallCount == 1)
    }

    @Test func aFailedRefreshExpiresTheSessionOnce() async throws {
        let (sut, authService, keychain) = makeSUT()
        try keychain.save("stored-refresh", for: KeychainKey.refreshToken)
        authService.refreshResult = .failure(
            APIError.server(status: 401, code: "REFRESH_REUSE_DETECTED", detail: "reused")
        )

        let alwaysUnauthorized: @Sendable () async throws -> String = {
            throw APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
        }
        async let a: () = { _ = try? await sut.authorizedRequest { try await alwaysUnauthorized() } }()
        async let b: () = { _ = try? await sut.authorizedRequest { try await alwaysUnauthorized() } }()
        _ = await [a, b]

        #expect(sut.state == .sessionExpired)
        #expect(authService.refreshCallCount <= 2)
    }

    @Test func logoutClearsTheStoredRefreshToken() async throws {
        /// A rotation completing after logout must not write a fresh token back into the
        /// Keychain that logout just cleared.
        let (sut, authService, keychain) = makeSUT()
        try seed(keychain, authService)

        await sut.logout()

        #expect(sut.state == .loggedOut)
        #expect((try? keychain.read(KeychainKey.refreshToken)) == nil)
    }
}
