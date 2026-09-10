import SwiftUI

/// Home — the answer to "what do I need to do today?".
///
/// This replaces a Phase 2 placeholder that rendered a fixed empty state on every launch,
/// which meant the daily mission lived four taps away at WARS → challenge → Verify and a
/// returning user had to remember that path. Every value on this screen is server-computed
/// and read from endpoints that already existed; Home creates no game state of its own.
struct HomeView: View {
    @Environment(\.challengesService) private var challengesService
    @Environment(\.gameService) private var gameService
    @Environment(\.verificationService) private var verificationService
    @Environment(\.mediaService) private var mediaService
    @Environment(\.healthKitService) private var healthKitService
    @Environment(SessionManager.self) private var sessionManager
    /// Lets the empty state send the user to the tab that can fix it, instead of telling
    /// them where to go and leaving them to find it.
    @Binding var selectedTab: MainTab

    @State private var viewModel: HomeViewModel?
    @State private var verifying: ChallengeDetail?
    @State private var verifyViewModel: VerifyViewModel?
    @State private var isLoadingMission = false

    var body: some View {
        NavigationStack {
            Group {
                if let viewModel {
                    content(viewModel)
                } else {
                    LoadingView(label: "Loading today…")
                }
            }
            .background(FWColor.background)
            .navigationTitle("Today")
        }
        .task {
            guard viewModel == nil else { return }
            viewModel = HomeViewModel(
                challenges: challengesService,
                games: gameService,
                sessionManager: sessionManager
            )
            await viewModel?.load()
        }
        .onChange(of: selectedTab) { _, tab in
            // `TabView` keeps every tab alive, so `.task` fires once and never again —
            // without this, coming back to Home after logging a mission elsewhere would
            // show yesterday's answer. Reloads rather than loads, so returning to the tab
            // never blanks what is already on screen.
            guard tab == .home else { return }
            Task { await viewModel?.reload() }
        }
        .sheet(item: $verifying) { challenge in
            let verify = verifyViewModel ?? VerifyViewModel(
                challenge: challenge,
                challenges: challengesService,
                verification: verificationService,
                health: healthKitService,
                media: mediaService
            )
            VerifyView(
                viewModel: verify,
                onCompleted: {
                    verifying = nil
                    verifyViewModel = nil
                    // The day's status is the server's to report — re-read it.
                    Task { await viewModel?.reload() }
                }
            )
            .onAppear { verifyViewModel = verify }
        }
    }

    @ViewBuilder
    private func content(_ model: HomeViewModel) -> some View {
        switch model.state {
        case .loading:
            LoadingView(label: "Loading today…")

        case .networkError:
            NetworkErrorView { Task { await model.load() } }

        case .unauthorized:
            UnauthorizedView { Task { await sessionManager.logout() } }

        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await model.load() } }
            )

        case .loaded:
            if model.missions.isEmpty {
                emptyState
            } else {
                missionList(model)
            }
        }
    }

    /// No active war. Honest and actionable — no invented statistics, no social proof.
    private var emptyState: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                SectionHeader(
                    eyebrow: "NO ACTIVE WAR",
                    title: "Nothing to do today.",
                    subtitle: "A war is a daily target you and your squad race on. "
                        + "Start one, or join a friend's with their code."
                )
                VStack(spacing: FWSpacing.sm + 2) {
                    FITWARPrimaryButton(title: "START A WAR") { openTab(.wars) }
                    FITWARSecondaryButton(title: "JOIN WITH A CODE") { openTab(.squad) }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func missionList(_ model: HomeViewModel) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                if let primary = model.primary {
                    TodaysMissionCard(
                        mission: primary,
                        isBusy: isLoadingMission,
                        onLog: { Task { await openVerify(for: primary) } }
                    )
                }

                if let xp = model.xp {
                    LevelProgress(xp: xp)
                }

                if !model.others.isEmpty {
                    VStack(alignment: .leading, spacing: FWSpacing.md) {
                        Text("YOUR OTHER WARS")
                            .font(FWTypography.eyebrowLabel)
                            .tracking(FWTracking.eyebrow)
                            .foregroundStyle(FWColor.textDim2)
                        ForEach(model.others) { mission in
                            MissionRow(mission: mission) {
                                Task { await openVerify(for: mission) }
                            }
                        }
                    }
                }

                Spacer(minLength: 0)
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .refreshable { await model.reload() }
    }

    /// Verify needs the full `ChallengeDetail`; Home only lists summaries, so it is
    /// fetched on demand rather than eagerly for every card.
    private func openVerify(for mission: TodaysMission) async {
        guard !isLoadingMission else { return }
        isLoadingMission = true
        defer { isLoadingMission = false }
        verifying = try? await sessionManager.authorizedRequest {
            try await challengesService.fetchChallenge(id: mission.challenge.id)
        }
    }

    private func openTab(_ tab: MainTab) {
        selectedTab = tab
    }
}
