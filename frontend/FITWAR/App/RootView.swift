import SwiftUI

/// The application root: switches on `SessionManager.state` exactly per Architecture
/// §10 — loggedOut/authenticating → auth flow, authenticated → main app (via
/// onboarding first if this authentication came from a fresh registration),
/// refreshing → a lightweight splash, sessionExpired → the reusable `UnauthorizedView`.
struct RootView: View {
    @Environment(SessionManager.self) private var sessionManager
    @State private var justRegistered = false
    @State private var onboardingComplete = false

    var body: some View {
        Group {
            switch sessionManager.state {
            case .loggedOut, .authenticating:
                AuthFlowView(onRegistered: {
                    justRegistered = true
                    onboardingComplete = false
                })

            case .refreshing:
                LoadingView(label: "Loading FITWAR…")

            case .authenticated:
                if justRegistered, !onboardingComplete {
                    OnboardingFlowView(onFinished: { onboardingComplete = true })
                } else {
                    MainTabView()
                }

            case .sessionExpired:
                UnauthorizedView(onLogIn: {
                    sessionManager.acknowledgeSessionExpired()
                })
            }
        }
        .animation(FWAnimation.entrance, value: sessionManagerStateTag)
        .background(FWColor.background)
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
