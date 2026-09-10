import SwiftUI

/// The application root: switches on `SessionManager.state` exactly per Architecture
/// §10 — loggedOut/authenticating → auth flow, authenticated → onboarding or the app,
/// refreshing → a lightweight splash, sessionExpired → the reusable `UnauthorizedView`.
///
/// Which of onboarding/app an authenticated user gets is resolved from the server rather
/// than inferred from how they signed in; see `AppRouteViewModel` for why the previous
/// callback-based version could not work.
struct RootView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.userService) private var userService
    @State private var router: AppRouteViewModel?

    var body: some View {
        Group {
            switch sessionManager.state {
            case .loggedOut, .authenticating:
                AuthFlowView()

            case .refreshing:
                LoadingView(label: "Loading FITWAR…")

            case .authenticated:
                authenticatedContent

            case .sessionExpired:
                UnauthorizedView(onLogIn: {
                    sessionManager.acknowledgeSessionExpired()
                })
            }
        }
        .animation(FWAnimation.entrance, value: sessionManagerStateTag)
        .background(FWColor.background)
        .task(id: sessionManagerStateTag) {
            // Runs whenever the session transitions. Resolving here — rather than in a
            // view that is about to be replaced — is the whole point: this view stays
            // mounted across the transition, so the work cannot be cancelled by it.
            guard case .authenticated = sessionManager.state else {
                router?.reset()
                return
            }
            if router == nil {
                router = AppRouteViewModel(
                    userService: userService, sessionManager: sessionManager
                )
            }
            if router?.route == .resolving {
                await router?.resolve()
            }
        }
    }

    @ViewBuilder
    private var authenticatedContent: some View {
        switch router?.route ?? .resolving {
        case .resolving:
            LoadingView(label: "Loading FITWAR…")

        case .onboarding(let stage, let displayName):
            OnboardingFlowView(
                startingAt: stage,
                // Prefilled with the name they gave at signup — asking for it twice is
                // work the product already has the answer to.
                initialDisplayName: displayName,
                onFinished: { router?.onboardingFinished() }
            )

        case .main:
            MainTabView()

        case .unavailable(let message):
            GenericStateView(
                symbol: "wifi.slash",
                title: "Couldn't load your profile",
                message: message,
                primaryActionTitle: "TRY AGAIN",
                primaryAction: { Task { await router?.resolve() } },
                secondaryActionTitle: "LOG OUT",
                secondaryAction: { Task { await sessionManager.logout() } }
            )
        }
    }

    /// `SessionState` isn't `Hashable` (it carries a `UUID` payload that varies per
    /// login) — this reduces it to just what should actually retrigger the transition
    /// animation, so re-authenticating as the same user doesn't glitch the transition.
    private var sessionManagerStateTag: Int {
        switch sessionManager.state {
        case .loggedOut: 0
        case .authenticating: 1
        case .authenticated: 2
        case .refreshing: 3
        case .sessionExpired: 4
        }
    }
}
