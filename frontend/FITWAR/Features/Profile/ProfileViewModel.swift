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

    private let userService: UserServiceProtocol
    private let sessionManager: SessionManager

    init(userService: UserServiceProtocol, sessionManager: SessionManager) {
        self.userService = userService
        self.sessionManager = sessionManager
    }

    func load() async {
        loadState = .loading
        do {
            let user = try await sessionManager.authorizedRequest {
                try await self.userService.fetchCurrentUser()
            }
            loadState = .loaded(user)
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

    /// `xp_total` is real, persisted data (Phase 1's `UserProfile.xp_total`, always 0
    /// today since nothing awards XP yet). `level` is a small, clearly-provisional
    /// formula on top of it — NOT the real leveling system (that belongs to the XP
    /// domain, a later phase) — documented here rather than left unexplained.
    static func provisionalLevel(forXP xp: Int) -> Int {
        1 + xp / 1000
    }
}
