import SwiftUI

/// Navigation coordinator for the logged-out flow: Login is the root, Register
/// pushes from it. `onRegistered` bubbles up to `RootView` so it knows to route
/// through onboarding next (this phase's §12).
private enum AuthRoute: Hashable {
    case login
    case register
}

struct AuthFlowView: View {
    @Environment(SessionManager.self) private var sessionManager
    @State private var path = NavigationPath()
    var onRegistered: () -> Void

    var body: some View {
        NavigationStack(path: $path) {
            WelcomeLandingView(
                onGetStarted: { path.append(AuthRoute.register) },
                onLogin: { path.append(AuthRoute.login) }
            )
            .navigationDestination(for: AuthRoute.self) { route in
                switch route {
                case .login:
                    LoginView(sessionManager: sessionManager, onGoToRegister: { path.append(AuthRoute.register) })
                        .toolbar(.hidden, for: .navigationBar)
                case .register:
                    RegisterView(sessionManager: sessionManager, onBack: { path.removeLast() })
                        .toolbar(.hidden, for: .navigationBar)
                        .navigationBarBackButtonHidden(true)
                }
            }
            .toolbar(.hidden, for: .navigationBar)
        }
        .onChange(of: sessionManager.state) { _, newState in
            if case .authenticated = newState, !path.isEmpty {
                // Registration just succeeded from the pushed Register screen.
                onRegistered()
            }
        }
    }
}
