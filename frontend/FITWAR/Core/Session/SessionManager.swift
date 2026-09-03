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

    /// The current access token, for the one caller that cannot use `APIClient`: a
    /// WebSocket handshake can't carry custom headers, so the token goes in the query
    /// string instead (see `WebSocketRealtimeClient`).
    var currentAccessToken: String? { accessToken }

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

    /// The single in-flight refresh, if one is running. Every concurrent caller awaits
    /// this same task rather than starting its own.
    private var refreshTask: Task<Void, Error>?

    /// Refresh the token pair, coalescing concurrent attempts into one network call.
    ///
    /// This must be single-flight, and the reason is not efficiency. Refresh tokens
    /// rotate and the server treats a second presentation of an already-rotated token as
    /// theft: it revokes the **entire token family**. Two screens hitting 401 at the same
    /// moment would each read the same stored token and each POST it — the first rotates
    /// successfully, the second is reuse, and the server correctly destroys the session.
    /// The user is silently logged out for doing nothing worse than opening two tabs of
    /// their own app.
    ///
    /// Coalescing here means one presentation per rotation no matter how many callers
    /// race. Because this type is `@MainActor`, the check-and-assign below cannot
    /// interleave — there is no window between reading `refreshTask` and setting it.
    private func refreshTokens() async throws {
        if let existing = refreshTask {
            // Someone else is already rotating. Wait for their result and use the token
            // they stored; starting a second rotation is what triggers the revocation.
            try await existing.value
            return
        }

        let task = Task<Void, Error> { [weak self] in
            guard let self else { return }
            guard let refreshToken = try self.keychain.read(KeychainKey.refreshToken) else {
                throw APIError.server(
                    status: 401, code: "REFRESH_INVALID", detail: "No refresh token stored."
                )
            }
            let tokens = try await self.authService.refresh(refreshToken: refreshToken)
            try self.applyTokens(tokens.accessToken, tokens.refreshToken)
        }
        refreshTask = task
        defer { refreshTask = nil }
        try await task.value
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
        // Cancel first: a refresh still in flight would otherwise finish afterwards and
        // write a freshly rotated token straight back into the Keychain this just
        // cleared, resurrecting a session the user ended.
        refreshTask?.cancel()
        refreshTask = nil
        accessToken = nil
        try? keychain.delete(KeychainKey.refreshToken)
        state = newState
    }
}
