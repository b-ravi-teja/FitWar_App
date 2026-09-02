import Foundation
import Observation

enum SessionState: Equatable {
    case loggedOut
    case authenticating
    case authenticated(userId: UUID)
    case refreshing
    case sessionExpired
}

/// Owns auth state only — token lifecycle, not profile data (that's `UserService` +
/// `ProfileViewModel`'s job). The app root (`RootView`) reacts to `state` directly:
/// loggedOut → auth flow, authenticated → main app, sessionExpired → a reusable
/// `UnauthorizedView` before returning to login.
@MainActor
@Observable
final class SessionManager {
    private(set) var state: SessionState = .loggedOut

    /// The signed-in user's id, when there is one. Screens use this to mark "(you)" in
    /// a roster or leaderboard without each one fetching `/me` just to learn its own id.
    var currentUserId: UUID? {
        if case .authenticated(let userId) = state { return userId }
        return nil
    }

    private let authService: AuthServiceProtocol
    private let keychain: KeychainStoring
    private let apiClient: APIClient
    private var accessToken: String?

    init(authService: AuthServiceProtocol, keychain: KeychainStoring, apiClient: APIClient) {
        self.authService = authService
        self.keychain = keychain
        self.apiClient = apiClient
        apiClient.accessTokenProvider = { [weak self] in
            await self?.accessToken
        }
    }

    /// Called once at app launch: silently resumes a session from the stored refresh
    /// token, or lands on `.loggedOut` if there isn't one / it's no longer valid.
    func bootstrap() async {
        guard let refreshToken = try? keychain.read(KeychainKey.refreshToken) else {
            state = .loggedOut
            return
        }
        state = .refreshing
        do {
            let tokens = try await authService.refresh(refreshToken: refreshToken)
            try applyTokens(tokens.accessToken, tokens.refreshToken)
        } catch {
            await clearSession(newState: .loggedOut)
        }
    }

    func login(email: String, password: String) async throws {
        state = .authenticating
        do {
            let session = try await authService.login(email: email, password: password)
            accessToken = session.accessToken
            try keychain.save(session.refreshToken, for: KeychainKey.refreshToken)
            state = .authenticated(userId: session.userId)
        } catch {
            state = .loggedOut
            throw error
        }
    }

    func register(email: String, password: String, displayName: String) async throws {
        state = .authenticating
        do {
            let session = try await authService.register(email: email, password: password, displayName: displayName)
            accessToken = session.accessToken
            try keychain.save(session.refreshToken, for: KeychainKey.refreshToken)
            state = .authenticated(userId: session.userId)
        } catch {
            state = .loggedOut
            throw error
        }
    }

    func logout() async {
        if let refreshToken = try? keychain.read(KeychainKey.refreshToken) {
            try? await authService.logout(refreshToken: refreshToken)
        }
        await clearSession(newState: .loggedOut)
    }

    /// Call this from `UnauthorizedView`'s primary action once the user acknowledges
    /// the expiry — moves from `.sessionExpired` to `.loggedOut` so `RootView` shows Login.
    func acknowledgeSessionExpired() {
        state = .loggedOut
    }

    /// Routes any authenticated call through automatic refresh-and-retry-once. This is
    /// the one place that logic lives, so feature ViewModels never reimplement it:
    /// `try await sessionManager.authorizedRequest { try await userService.fetchCurrentUser() }`.
    func authorizedRequest<T>(_ operation: () async throws -> T) async throws -> T {
        do {
            return try await operation()
        } catch let error as APIError where error.isUnauthorized {
            do {
                try await refreshTokens()
                return try await operation()
            } catch {
                await clearSession(newState: .sessionExpired)
                throw error
            }
        }
    }

    private func refreshTokens() async throws {
        guard let refreshToken = try keychain.read(KeychainKey.refreshToken) else {
            throw APIError.server(status: 401, code: "REFRESH_INVALID", detail: "No refresh token stored.")
        }
        let tokens = try await authService.refresh(refreshToken: refreshToken)
        try applyTokens(tokens.accessToken, tokens.refreshToken)
    }

    private func applyTokens(_ access: String, _ refresh: String) throws {
        guard let userId = JWTInspector.subject(of: access) else {
            throw APIError.decodingFailed
        }
        accessToken = access
        try keychain.save(refresh, for: KeychainKey.refreshToken)
        state = .authenticated(userId: userId)
    }

    private func clearSession(newState: SessionState) async {
        accessToken = nil
        try? keychain.delete(KeychainKey.refreshToken)
        state = newState
    }
}
