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

private struct VerificationServiceKey: EnvironmentKey {
    static let defaultValue: VerificationServiceProtocol = VerificationService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct BattlesServiceKey: EnvironmentKey {
    static let defaultValue: BattlesServiceProtocol = BattlesService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct GameServiceKey: EnvironmentKey {
    static let defaultValue: GameServiceProtocol = GameService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct MediaServiceKey: EnvironmentKey {
    static let defaultValue: MediaServiceProtocol = MediaService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct ChatServiceKey: EnvironmentKey {
    static let defaultValue: ChatServiceProtocol = ChatService(
        client: APIClient(baseURL: AppConfig.apiBaseURL)
    )
}

private struct RealtimeClientKey: EnvironmentKey {
    static let defaultValue: RealtimeClientProtocol = WebSocketRealtimeClient()
}

private struct HealthKitServiceKey: EnvironmentKey {
    static let defaultValue: HealthKitServicing = HealthKitService()
}

extension EnvironmentValues {
    var verificationService: VerificationServiceProtocol {
        get { self[VerificationServiceKey.self] }
        set { self[VerificationServiceKey.self] = newValue }
    }

    var battlesService: BattlesServiceProtocol {
        get { self[BattlesServiceKey.self] }
        set { self[BattlesServiceKey.self] = newValue }
    }

    var gameService: GameServiceProtocol {
        get { self[GameServiceKey.self] }
        set { self[GameServiceKey.self] = newValue }
    }

    var mediaService: MediaServiceProtocol {
        get { self[MediaServiceKey.self] }
        set { self[MediaServiceKey.self] = newValue }
    }

    var chatService: ChatServiceProtocol {
        get { self[ChatServiceKey.self] }
        set { self[ChatServiceKey.self] = newValue }
    }

    var realtimeClient: RealtimeClientProtocol {
        get { self[RealtimeClientKey.self] }
        set { self[RealtimeClientKey.self] = newValue }
    }

    var healthKitService: HealthKitServicing {
        get { self[HealthKitServiceKey.self] }
        set { self[HealthKitServiceKey.self] = newValue }
    }

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
