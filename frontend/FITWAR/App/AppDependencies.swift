import Foundation

/// Composition root — the one place concrete implementations get wired together.
/// Everything downstream (views, view models) depends on protocols, not this type.
@MainActor
final class AppDependencies {
    let apiClient: APIClient
    let authService: AuthServiceProtocol
    let userService: UserServiceProtocol
    let groupsService: GroupsServiceProtocol
    let challengesService: ChallengesServiceProtocol
    let verificationService: VerificationServiceProtocol
    let keychain: KeychainStoring
    let sessionManager: SessionManager
    let themeManager: ThemeManager
    let healthConnector: HealthConnector
    let healthKitService: HealthKitServicing

    init() {
        let client = APIClient(baseURL: AppConfig.apiBaseURL)
        apiClient = client
        authService = AuthService(client: client)
        userService = UserService(client: client)
        groupsService = GroupsService(client: client)
        challengesService = ChallengesService(client: client)
        verificationService = VerificationService(client: client)
        keychain = KeychainStore()
        sessionManager = SessionManager(authService: authService, keychain: keychain, apiClient: client)
        themeManager = ThemeManager()
        healthConnector = UnimplementedHealthConnector()
        healthKitService = HealthKitService()

        #if DEBUG
        Self.applyUITestHooks(keychain: keychain)
        #endif
    }

    #if DEBUG
    /// Test-only launch hooks, compiled into Debug builds only, so `FITWARUITests`
    /// can put the app into a deterministic session state without hitting the UI —
    /// "logged out" clears any stale simulator Keychain state, "logged in" seeds a
    /// real refresh token the UI test obtained by calling the local backend directly
    /// (not a fake token — `SessionManager.bootstrap()` still validates it for real).
    private static func applyUITestHooks(keychain: KeychainStoring) {
        let arguments = ProcessInfo.processInfo.arguments
        let environment = ProcessInfo.processInfo.environment

        if arguments.contains("-UITestClearSession") {
            try? keychain.delete(KeychainKey.refreshToken)
        }
        if let seedToken = environment["UITEST_SEED_REFRESH_TOKEN"] {
            try? keychain.save(seedToken, for: KeychainKey.refreshToken)
        }
    }
    #endif
}
