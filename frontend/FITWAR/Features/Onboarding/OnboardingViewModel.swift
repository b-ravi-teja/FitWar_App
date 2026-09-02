import Foundation

enum OnboardingStep: Int, CaseIterable {
    case discipline, health, profile
}

/// Coordinates `ob2`–`ob4` from the prototype (ob1 lives pre-auth now, see
/// `WelcomeLandingView`). Only `displayName` is persisted through the backend
/// (`PATCH /me`) — `fitnessLevel` has no backing column in the frozen schema
/// (Architecture's ERD has no such field), so it's held locally and never claimed
/// as submitted; see the Phase 2 report's notes rather than silently inventing a
/// backend field mid-phase.
@MainActor
@Observable
final class OnboardingViewModel {
    var step: OnboardingStep = .discipline
    var selectedDiscipline: String?
    var displayName: String
    var fitnessLevel: String?
    private(set) var isSubmitting = false
    private(set) var errorMessage: String?

    private let userService: UserServiceProtocol
    private let sessionManager: SessionManager
    private let healthConnector: HealthConnector

    let disciplines = ["Steps", "Running", "Strength", "Calories", "Endurance", "General"]
    let fitnessLevels = ["Casual", "Regular", "Athlete"]

    init(
        userService: UserServiceProtocol,
        sessionManager: SessionManager,
        healthConnector: HealthConnector,
        initialDisplayName: String = ""
    ) {
        self.userService = userService
        self.sessionManager = sessionManager
        self.healthConnector = healthConnector
        displayName = initialDisplayName
    }

    func pickDiscipline(_ name: String) {
        selectedDiscipline = name
        step = .health
    }

    /// Matches the prototype exactly: both buttons just advance (§15 — no fake
    /// connection state, Health Connect is never a real iOS integration).
    func connectHealth(_ provider: HealthProviderKind) async {
        _ = await healthConnector.requestConnection(for: provider)
        step = .profile
    }

    func skipHealth() {
        step = .profile
    }

    var canFinish: Bool {
        !displayName.trimmingCharacters(in: .whitespaces).isEmpty && !isSubmitting
    }

    /// Persists the only real field (`displayName`) via `PATCH /me`, added this
    /// phase (§25) specifically because onboarding needed somewhere real to submit
    /// to — not fabricated, not stored as a local-only stand-in for API persistence.
    func finish() async -> Bool {
        guard canFinish else { return false }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        do {
            _ = try await sessionManager.authorizedRequest {
                try await self.userService.updateDisplayName(self.displayName.trimmingCharacters(in: .whitespaces))
            }
            return true
        } catch {
            errorMessage = AuthErrorPresentation.message(for: error)
            return false
        }
    }
}
