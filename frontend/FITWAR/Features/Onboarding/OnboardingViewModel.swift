import Foundation
import Observation

/// Coordinates `ob2`–`ob4` from the prototype (ob1 lives pre-auth now, see
/// `WelcomeLandingView`).
///
/// Two things changed after the beta walkthrough found onboarding was being skipped:
///
/// 1. **Progress is persisted server-side after every step** (`PATCH /me`), so a user who
///    quits mid-flow resumes where they stopped instead of starting over, and a returning
///    user is never shown it again.
/// 2. **The HealthKit step calls the real Phase 4 service.** It previously used
///    `UnimplementedHealthConnector`, a Phase 2 stand-in that made no HealthKit call — so
///    even when onboarding *did* run, permission was never actually requested.
///
/// `fitnessLevel` still has no backing column in the frozen schema, so it is held locally
/// and never claimed as submitted.
@MainActor
@Observable
final class OnboardingViewModel {
    var step: OnboardingStage
    var selectedDiscipline: String?
    var displayName: String
    var fitnessLevel: String?
    private(set) var isSubmitting = false
    private(set) var errorMessage: String?
    /// Set when HealthKit itself is unusable on this device. The step still completes —
    /// a user without Health can still run manual-proof challenges — but the copy says
    /// so rather than pretending the connection worked.
    private(set) var healthUnavailable = false

    private let userService: UserServiceProtocol
    private let sessionManager: SessionManager
    private let health: HealthKitServicing

    let disciplines = ["Steps", "Running", "Strength", "Calories", "Endurance", "General"]
    let fitnessLevels = ["Casual", "Regular", "Athlete"]

    init(
        userService: UserServiceProtocol,
        sessionManager: SessionManager,
        health: HealthKitServicing,
        startingAt stage: OnboardingStage = .discipline,
        initialDisplayName: String = ""
    ) {
        self.userService = userService
        self.sessionManager = sessionManager
        self.health = health
        // `.completed` should never reach here (the router sends those users to Home),
        // but resuming at the last real step is the safe reading if it does.
        self.step = stage == .completed ? .profile : stage
        displayName = initialDisplayName
    }

    /// Which activity the HealthKit prompt asks for.
    ///
    /// The metric is chosen from the discipline the user just picked so the permission
    /// sheet names something they recognise. Disciplines HealthKit cannot measure
    /// (Strength → push-ups) fall back to steps: those challenges are verified by video
    /// proof anyway, and asking for an unsupported type would throw rather than prompt.
    var healthActivity: ActivityType {
        switch selectedDiscipline {
        case "Running", "Endurance": .distance
        case "Calories": .activeCalories
        default: .steps
        }
    }

    var isHealthAvailable: Bool { health.isAvailable }

    func pickDiscipline(_ name: String) async {
        selectedDiscipline = name
        await advance(to: .health)
    }

    /// Ask iOS for read access, then continue regardless of the answer.
    ///
    /// Continuing is not a shortcut: iOS never reports whether *read* access was granted
    /// (Architecture §21.5), so there is no denial to branch on. Blocking the flow on an
    /// unknowable outcome would strand the user. What the app can honestly say — whether
    /// anything was actually read — is said later, on the Verify screen.
    func connectHealth() async {
        guard !isSubmitting else { return }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        do {
            _ = try await health.requestAuthorization(for: healthActivity)
        } catch HealthKitError.unavailable, HealthKitError.unsupportedMetric {
            // No Health on this device, or a metric it cannot measure. Not an error the
            // user can act on, and not a reason to block onboarding.
            healthUnavailable = true
        } catch {
            healthUnavailable = true
        }
        await advance(to: .profile)
    }

    func skipHealth() async {
        await advance(to: .profile)
    }

    var canFinish: Bool {
        !displayName.trimmingCharacters(in: .whitespaces).isEmpty && !isSubmitting
    }

    /// Persist the display name and mark onboarding complete, in that order.
    ///
    /// Completion is only recorded if the name saved: marking it complete first would let
    /// a failed save strand the user with a half-finished profile and no way back.
    func finish() async -> Bool {
        guard canFinish else { return false }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        do {
            let trimmed = displayName.trimmingCharacters(in: .whitespaces)
            _ = try await sessionManager.authorizedRequest {
                try await self.userService.updateDisplayName(trimmed)
            }
            _ = try await sessionManager.authorizedRequest {
                try await self.userService.updateOnboardingStage(.completed)
            }
            return true
        } catch {
            errorMessage = DomainErrorPresentation.message(for: error)
            return false
        }
    }

    /// Move to the next step and record it server-side.
    ///
    /// The UI advances even if the write fails — a network blip must not block onboarding
    /// — but the step is not silently lost either: the next successful write, or the
    /// final `finish()`, brings the server back in line.
    private func advance(to next: OnboardingStage) async {
        step = next
        do {
            _ = try await sessionManager.authorizedRequest {
                try await self.userService.updateOnboardingStage(next)
            }
        } catch {
            // Progress is a convenience, not competitive state. Worst case the user
            // resumes one step earlier than they left off.
        }
    }
}
