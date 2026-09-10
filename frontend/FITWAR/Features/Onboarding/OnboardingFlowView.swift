import SwiftUI

struct OnboardingFlowView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.userService) private var userService
    @Environment(\.healthKitService) private var healthKitService
    /// Where the server says this user left off.
    let startingAt: OnboardingStage
    /// The name from registration, so the profile step opens prefilled.
    var initialDisplayName: String = ""
    @State private var viewModel: OnboardingViewModel?
    var onFinished: () -> Void

    var body: some View {
        Group {
            if let viewModel {
                switch viewModel.step {
                case .discipline:
                    OnboardingDisciplineView(viewModel: viewModel)
                case .health:
                    OnboardingHealthView(viewModel: viewModel)
                case .profile, .completed:
                    OnboardingProfileView(viewModel: viewModel, onFinished: onFinished)
                }
            } else {
                LoadingView()
            }
        }
        .onAppear {
            if viewModel == nil {
                viewModel = OnboardingViewModel(
                    userService: userService,
                    sessionManager: sessionManager,
                    health: healthKitService,
                    startingAt: startingAt,
                    initialDisplayName: initialDisplayName
                )
            }
        }
        .animation(FWAnimation.entrance, value: viewModel?.step)
    }
}
