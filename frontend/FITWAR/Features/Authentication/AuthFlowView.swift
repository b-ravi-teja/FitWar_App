import SwiftUI

/// Navigation coordinator for the logged-out flow: Login is the root, Register
/// pushes from it.
///
/// It deliberately no longer signals "just registered" upward. That callback fired from
/// an `.onChange` on a view `RootView` replaces the moment the session authenticates, so
/// it raced its own teardown and lost — onboarding was skipped for every new account.
/// Whether a user needs onboarding is now read from the server (`AppRouteViewModel`),
/// which is also the only version that survives reinstall and logout/login.
private enum AuthRoute: Hashable {
    case login
    case register
}

struct AuthFlowView: View {
    @Environment(SessionManager.self) private var sessionManager
    @State private var path = NavigationPath()

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
    }
}
