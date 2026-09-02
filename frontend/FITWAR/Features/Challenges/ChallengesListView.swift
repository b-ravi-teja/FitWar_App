import SwiftUI

/// The WARS tab. Reproduces the prototype's `challenges` screen — headline + "+" button,
/// segmented tabs, challenge cards — with ACTIVE/COMPLETED only (ADR 0001 drops DISCOVER).
struct ChallengesListView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.challengesService) private var challengesService
    @Environment(\.groupsService) private var groupsService

    @State private var viewModel: ChallengesListViewModel?
    @State private var path: [UUID] = []
    @State private var creatingInGroup: GroupSummary?
    @State private var showGroupPicker = false

    var body: some View {
        NavigationStack(path: $path) {
            content
                .background(FWColor.background)
                .navigationDestination(for: UUID.self) { challengeId in
                    ChallengeDetailView(challengeId: challengeId)
                        .toolbar(.hidden, for: .navigationBar)
                }
                .toolbar(.hidden, for: .navigationBar)
        }
        .task {
            if viewModel == nil {
                viewModel = ChallengesListViewModel(
                    challengesService: challengesService,
                    groupsService: groupsService,
                    sessionManager: sessionManager
                )
            }
            await viewModel?.load()
        }
        .fullScreenCover(item: $creatingInGroup) { group in
            CreateChallengeFlowView(group: group) { created in
                creatingInGroup = nil
                Task {
                    await viewModel?.reload()
                    path.append(created.id)
                }
            } onCancel: {
                creatingInGroup = nil
            }
        }
        .confirmationDialog(
            "Which squad?", isPresented: $showGroupPicker, titleVisibility: .visible
        ) {
            ForEach(viewModel?.groups ?? []) { group in
                Button(group.name) { creatingInGroup = group }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("A challenge always lives inside a squad.")
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state {
        case .none, .loading:
            LoadingView(label: "Loading your wars…")
        case .loaded:
            loaded
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel?.load() } })
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel?.load() } }
            )
        case .unauthorized:
            UnauthorizedView(onLogIn: { viewModel?.acknowledgeUnauthorized() })
        }
    }

    @ViewBuilder
    private var loaded: some View {
        if let viewModel {
            @Bindable var model = viewModel

            ScrollView {
                VStack(alignment: .leading, spacing: FWSpacing.xl) {
                    header

                    SegmentedTabs(
                        options: ChallengesListViewModel.Tab.allCases.map(\.rawValue),
                        selection: Binding(
                            get: { model.selectedTab.rawValue },
                            set: { model.selectedTab = .init(rawValue: $0) ?? .active }
                        )
                    )

                    if viewModel.challenges.isEmpty {
                        emptyState(for: viewModel)
                    } else {
                        VStack(spacing: FWSpacing.md) {
                            ForEach(viewModel.challenges) { challenge in
                                Button {
                                    path.append(challenge.id)
                                } label: {
                                    challengeCard(challenge)
                                }
                                .buttonStyle(FWPressableStyle())
                            }
                        }
                    }
                }
                .padding(.horizontal, FWSpacing.screenHorizontal)
                .padding(.top, 62)
                .padding(.bottom, FWSpacing.xxl)
            }
            .refreshable { await viewModel.reload() }
        }
    }

    private func challengeCard(_ challenge: ChallengeSummary) -> some View {
        ChallengeCard(
            name: challenge.name,
            meta: challenge.metaLine,
            statusText: challenge.status.displayName,
            statusTone: statusTone(for: challenge.status),
            // The design's big number is the day's verified metric. There isn't one
            // until Phase 4, so this shows the challenge's daily target — real
            // configuration — rather than a placeholder score.
            progressLabel: challenge.targetLabel,
            // The design's trailing slot is a rank. Ranking needs the leaderboard
            // domain, so this shows days remaining — real, and not a repeat of the
            // day count already in the meta line above.
            rankLabel: challenge.remainingLabel,
            progress: challenge.scheduleProgress
        )
        .accessibilityLabel(
            "\(challenge.name), \(challenge.metaLine), target \(challenge.targetLabel)"
        )
    }

    private func statusTone(for status: ChallengeStatus) -> StatusBadge.Tone {
        switch status {
        case .active: .accent
        case .draft: .info
        case .completed: .neutral
        case .cancelled: .danger
        }
    }

    @ViewBuilder
    private func emptyState(for viewModel: ChallengesListViewModel) -> some View {
        if viewModel.selectedTab == .completed {
            EmptyStateView(
                title: "Your battlefield is empty.",
                message: "Nothing completed yet. Survive a war and it shows up here."
            )
        } else if viewModel.canCreate {
            EmptyStateView(
                title: "No wars running.",
                message: "Start one and drag your squad into it.",
                actionTitle: "CREATE A CHALLENGE",
                action: { showGroupPicker = true }
            )
        } else {
            EmptyStateView(
                title: "Join a squad first.",
                message: "Challenges live inside a squad. Create or join one from the SQUAD tab."
            )
        }
    }

    private var header: some View {
        HStack {
            Text("Challenges")
                .font(FWTypography.displayMedium)
                .foregroundStyle(FWColor.textPrimary)
            Spacer()
            Button {
                startCreate()
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(FWColor.onAccent)
                    .frame(width: 38, height: 38)
                    .background(FWColor.accent.opacity(viewModel?.canCreate == true ? 1 : 0.4))
                    .clipShape(Circle())
            }
            .buttonStyle(FWPressableStyle())
            .disabled(viewModel?.canCreate != true)
            .accessibilityLabel("Create a challenge")
        }
    }

    private func startCreate() {
        guard let groups = viewModel?.groups, !groups.isEmpty else { return }
        // One squad is the common case — don't make someone pick from a list of one.
        if groups.count == 1 {
            creatingInGroup = groups[0]
        } else {
            showGroupPicker = true
        }
    }
}
