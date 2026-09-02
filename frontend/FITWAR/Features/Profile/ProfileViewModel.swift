import Foundation

enum ProfileLoadState: Equatable {
    case loading
    case loaded(User)
    case networkError
    case serverError
    case unauthorized
}

@MainActor
@Observable
final class ProfileViewModel {
    private(set) var loadState: ProfileLoadState = .loading

    /// Server-computed XP, level and streak. Nil until loaded, and never derived
    /// locally — Phase 5 moved leveling to the server so there is one authority.
    private(set) var xpSummary: XPSummary?

    private let userService: UserServiceProtocol
    private let gameService: GameServiceProtocol
    private let sessionManager: SessionManager

    init(
        userService: UserServiceProtocol,
        gameService: GameServiceProtocol,
        sessionManager: SessionManager
    ) {
        self.userService = userService
        self.gameService = gameService
        self.sessionManager = sessionManager
    }

    func load() async {
        loadState = .loading
        do {
            let user = try await sessionManager.authorizedRequest {
                try await self.userService.fetchCurrentUser()
            }
            loadState = .loaded(user)
            // Secondary: the profile still renders without it, so a failure here
            // degrades the level badge rather than the whole screen.
            xpSummary = try? await sessionManager.authorizedRequest {
                try await self.gameService.fetchXPSummary()
            }
        } catch let error as APIError {
            loadState = classify(error)
        } catch {
            loadState = .serverError
        }
    }

    private func classify(_ error: APIError) -> ProfileLoadState {
        switch error {
        case .noConnection, .timeout: .networkError
        case .server(let status, _, _) where status == 401: .unauthorized
        case .server, .decodingFailed, .unknown: .serverError
        }
    }

    func logout() async {
        await sessionManager.logout()
    }

}
