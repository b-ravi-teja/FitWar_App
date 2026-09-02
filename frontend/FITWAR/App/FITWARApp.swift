import SwiftUI

@main
struct FITWARApp: App {
    @State private var dependencies = AppDependencies()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(dependencies.sessionManager)
                .environment(dependencies.themeManager)
                .environment(\.authService, dependencies.authService)
                .environment(\.userService, dependencies.userService)
                .environment(\.healthConnector, dependencies.healthConnector)
                .environment(\.groupsService, dependencies.groupsService)
                .environment(\.challengesService, dependencies.challengesService)
                .environment(\.verificationService, dependencies.verificationService)
                .environment(\.healthKitService, dependencies.healthKitService)
                .preferredColorScheme(dependencies.themeManager.preference.colorScheme)
                .task {
                    await dependencies.sessionManager.bootstrap()
                }
        }
    }
}
