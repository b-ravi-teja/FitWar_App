import Foundation
import Observation

/// Decides what an authenticated user should see: onboarding, or the app.
///
/// This exists because the previous mechanism could not work. `AuthFlowView` signalled
/// "just registered" from an `.onChange`, but `RootView` swaps that view out the instant
/// the session becomes authenticated — so the callback raced its own view's teardown and
/// lost, and onboarding was skipped for every new account. The same handler also fired on
/// *login* from a pushed screen, so a returning user could be shown onboarding instead.
///
/// The fix is to stop inferring the answer from a transient UI event and read it from the
/// one place that actually knows: the server. `GET /me` carries `onboarding_stage`, which
/// survives reinstall, a second device, and logout/login.
@MainActor
@Observable
final class AppRouteViewModel {
    enum Route: Equatable {
        case resolving
        /// Show onboarding, starting at this step, with the name they registered under.
        case onboarding(OnboardingStage, displayName: String)
        case main
        /// `/me` could not be reached. Deliberately its own state rather than falling
        /// through to Home: guessing "onboarded" for a brand-new user would strand them
        /// on an empty screen with no HealthKit permission and no way back to the flow.
        case unavailable(String)
    }

    private(set) var route: Route = .resolving

    private let userService: UserServiceProtocol
    private let sessionManager: SessionManager

    init(userService: UserServiceProtocol, sessionManager: SessionManager) {
        self.userService = userService
        self.sessionManager = sessionManager
    }

    /// Resolve where this user belongs. Called when a session becomes authenticated.
    func resolve() async {
        route = .resolving
        do {
            let user = try await sessionManager.authorizedRequest {
                try await userService.fetchCurrentUser()
            }
            route = user.onboardingStage.isComplete
                ? .main
                : .onboarding(user.onboardingStage, displayName: user.displayName)
        } catch {
            route = .unavailable(DomainErrorPresentation.message(for: error))
        }
    }

    /// Onboarding reported that it finished. The server was already told; this just moves
    /// the UI without a second round trip.
    func onboardingFinished() {
        route = .main
    }

    /// Drop the resolved route so the next authenticated session resolves again — a
    /// different account will not inherit this one's answer.
    func reset() {
        route = .resolving
    }
}
