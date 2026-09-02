import SwiftUI

struct OnboardingFlowView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.userService) private var userService
    @Environment(\.healthConnector) private var healthConnector
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
                case .profile:
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
                    healthConnector: healthConnector
                )
            }
        }
        .animation(FWAnimation.entrance, value: viewModel?.step)
    }
}
