import SwiftUI

/// Protocol-typed dependencies injected via `EnvironmentValues` — `@Environment(Type.self)`
/// only works for `@Observable` classes, not protocol existentials, so these get the
/// classic `EnvironmentKey` treatment. `SessionManager`/`ThemeManager` (both
/// `@Observable`) are injected the normal way in `FITWARApp`.
private struct AuthServiceKey: EnvironmentKey {
    static let defaultValue: AuthServiceProtocol = AuthService(client: APIClient(baseURL: AppConfig.apiBaseURL))
}

private struct UserServiceKey: EnvironmentKey {
    static let defaultValue: UserServiceProtocol = UserService(client: APIClient(baseURL: AppConfig.apiBaseURL))
}

private struct HealthConnectorKey: EnvironmentKey {
    static let defaultValue: HealthConnector = UnimplementedHealthConnector()
}

private struct GroupsServiceKey: EnvironmentKey {
    static let defaultValue: GroupsServiceProtocol = GroupsService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct ChallengesServiceKey: EnvironmentKey {
    static let defaultValue: ChallengesServiceProtocol = ChallengesService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

extension EnvironmentValues {
    var authService: AuthServiceProtocol {
        get { self[AuthServiceKey.self] }
        set { self[AuthServiceKey.self] = newValue }
    }

    var userService: UserServiceProtocol {
        get { self[UserServiceKey.self] }
        set { self[UserServiceKey.self] = newValue }
    }

    var healthConnector: HealthConnector {
        get { self[HealthConnectorKey.self] }
        set { self[HealthConnectorKey.self] = newValue }
    }

    var groupsService: GroupsServiceProtocol {
        get { self[GroupsServiceKey.self] }
        set { self[GroupsServiceKey.self] = newValue }
    }

    var challengesService: ChallengesServiceProtocol {
        get { self[ChallengesServiceKey.self] }
        set { self[ChallengesServiceKey.self] = newValue }
    }
}
