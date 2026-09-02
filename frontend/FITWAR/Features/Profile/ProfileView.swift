import SwiftUI

/// The one real screen this phase builds beyond auth/onboarding (§18). Reproduces
/// the prototype's Profile layout (avatar + name + level badge, stats grid,
/// achievements, history), but Challenges/XP/Achievements don't exist as backend
/// domains yet — so those sections show an honest empty state (reusing
/// `EmptyStateView`) instead of fabricated numbers. Only `displayName` and
/// `xpTotal` are real, persisted values from `GET /me`.
struct ProfileView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.userService) private var userService
    @State private var viewModel: ProfileViewModel?

    var body: some View {
        NavigationStack {
            content
                .background(FWColor.background)
                .navigationTitle("You")
        }
        .task {
            if viewModel == nil {
                viewModel = ProfileViewModel(userService: userService, sessionManager: sessionManager)
            }
            await viewModel?.load()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.loadState {
        case .none, .loading:
            LoadingView(label: "Loading profile…")
        case .loaded(let user):
            loaded(user)
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel?.load() } })
        case .serverError:
            ServerErrorView(onRetry: { Task { await viewModel?.load() } })
        case .unauthorized:
            UnauthorizedView(onLogIn: { sessionManager.acknowledgeSessionExpired() })
        }
    }

    private func loaded(_ user: User) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                HStack(spacing: FWSpacing.lg) {
                    AvatarView(size: 76, initials: initials(for: user.displayName))
                    VStack(alignment: .leading, spacing: FWSpacing.xs + 1) {
                        Text(user.displayName)
                            .font(FWTypography.displayLarge)
                            .foregroundStyle(FWColor.textPrimary)
                        HStack(spacing: FWSpacing.xs + 1) {
                            StatusBadge(text: "LEVEL \(ProfileViewModel.provisionalLevel(forXP: user.xpTotal))", tone: .accent)
                        }
                    }
                }

                StatCardGrid(stats: [
                    ("\(user.xpTotal)", "XP"),
                    ("—", "CHALLENGES"),
                    ("—", "WINS"),
                    ("—", "LOSSES"),
                ])

                VStack(alignment: .leading, spacing: FWSpacing.md) {
                    Text("ACHIEVEMENTS")
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)

                    EmptyStateView(
                        title: "Nothing yet",
                        message: "Achievements unlock once challenges are live."
                    )
                }

                VStack(alignment: .leading, spacing: FWSpacing.md) {
                    Text("CHALLENGE HISTORY")
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)

                    EmptyStateView(
                        title: "No challenges yet",
                        message: "Your completed wars will show up here."
                    )
                }

                FITWARSecondaryButton(title: "LOG OUT") {
                    Task { await viewModel?.logout() }
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.top, FWSpacing.xl)
            .padding(.bottom, FWSpacing.xxxl)
        }
    }

    private func initials(for name: String) -> String {
        String(name.prefix(1)).uppercased()
    }
}
