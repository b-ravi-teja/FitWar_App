import SwiftUI

/// The Group screen — header (name, member/challenge meta, avatar stack), segmented
/// tabs, then ROSTER or FEED. Reproduces the prototype's `group` screen exactly, minus
/// the CHAT tab: realtime chat is a later phase, and a tab that opens onto nothing is
/// worse than a tab that isn't there yet.
struct GroupDetailView: View {
    let groupId: UUID
    var onLeft: () -> Void

    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.groupsService) private var groupsService
    @Environment(\.challengesService) private var challengesService
    @Environment(\.dismiss) private var dismiss

    @State private var viewModel: GroupDetailViewModel?
    @State private var showLeaveConfirmation = false

    var body: some View {
        content
            .background(FWColor.background)
            .task {
                if viewModel == nil {
                    viewModel = GroupDetailViewModel(
                        groupId: groupId,
                        groupsService: groupsService,
                        challengesService: challengesService,
                        sessionManager: sessionManager,
                        currentUserId: sessionManager.currentUserId
                    )
                }
                await viewModel?.load()
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state {
        case .none, .loading:
            LoadingView(label: "Loading squad…")
        case .loaded(let loaded):
            body(for: loaded)
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel?.load() } })
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel?.load() } },
                secondaryActionTitle: "Back to squads",
                secondaryAction: { dismiss() }
            )
        case .unauthorized:
            UnauthorizedView(onLogIn: { viewModel?.acknowledgeUnauthorized() })
        }
    }

    private func body(for loaded: GroupDetailViewModel.Content) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.lg + 2) {
                header(loaded.group)
                tabs
                    .padding(.horizontal, FWSpacing.screenHorizontal)

                switch viewModel?.selectedTab ?? .roster {
                case .roster:
                    roster(loaded)
                case .feed:
                    feed(loaded)
                }
            }
            .padding(.top, 60)
            .padding(.bottom, FWSpacing.xxl)
        }
        .refreshable { await viewModel?.reload() }
        .confirmationDialog(
            "Leave \(loaded.group.name)?",
            isPresented: $showLeaveConfirmation,
            titleVisibility: .visible
        ) {
            Button("Leave squad", role: .destructive) {
                Task {
                    if await viewModel?.leaveGroup() == true {
                        onLeft()
                    }
                }
            }
            Button("Stay", role: .cancel) {}
        } message: {
            Text("You'll lose access to this squad's challenges and roster.")
        }
    }

    private func header(_ group: GroupDetail) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.sm + 2) {
            HStack {
                CircleIconButton(systemName: "chevron.left", accessibilityLabel: "Back") {
                    dismiss()
                }
                Spacer()
                if group.myRole != .owner {
                    CircleIconButton(
                        systemName: "ellipsis", accessibilityLabel: "Squad options"
                    ) {
                        showLeaveConfirmation = true
                    }
                }
            }

            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: FWSpacing.xs) {
                    Text(group.name)
                        .font(FWTypography.displayMedium)
                        .foregroundStyle(FWColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(group.metaLine)
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                }
                Spacer(minLength: FWSpacing.md)
                AvatarStack(count: min(group.memberCount, 4), size: 28)
                    .padding(.top, FWSpacing.xxs)
            }

            if group.myRole.isAdmin {
                JoinCodeCard(code: group.joinCode)
                    .padding(.top, FWSpacing.sm)
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    private var tabs: some View {
        Group {
            if let viewModel {
                @Bindable var model = viewModel
                SegmentedTabs(
                    options: GroupDetailViewModel.Tab.allCases.map(\.rawValue),
                    selection: Binding(
                        get: { model.selectedTab.rawValue },
                        set: { model.selectedTab = .init(rawValue: $0) ?? .roster }
                    )
                )
            }
        }
    }

    private func roster(_ loaded: GroupDetailViewModel.Content) -> some View {
        VStack(spacing: FWSpacing.sm) {
            ForEach(loaded.members) { member in
                RosterRow(
                    displayName: member.displayName,
                    stateLabel: member.stateLabel,
                    // The design's trailing slot is a rank. Ranking needs the
                    // leaderboard/XP domain, so it shows the member's role instead —
                    // real data — rather than an invented "#4".
                    trailingLabel: member.role.label,
                    isMe: viewModel?.isMe(member.userId) ?? false
                )
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    private func feed(_ loaded: GroupDetailViewModel.Content) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            if loaded.activity.isEmpty {
                EmptyStateView(
                    title: "Nothing's happened yet.",
                    message: "Squad activity shows up here as people join and start challenges."
                )
            } else {
                ForEach(loaded.activity) { entry in
                    ActivityRow(
                        who: entry.actorDisplayName,
                        what: entry.text,
                        when: RelativeTime.short(from: entry.occurredAt),
                        dotColor: entry.kind == "challenge_created" ? FWColor.accent : FWColor.blue
                    )
                }
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }
}

/// Compact relative timestamps ("18m", "5h", "3d") matching the design's feed labels.
enum RelativeTime {
    static func short(from date: Date, now: Date = Date()) -> String {
        let seconds = Int(now.timeIntervalSince(date))
        if seconds < 60 { return "now" }
        if seconds < 3600 { return "\(seconds / 60)m" }
        if seconds < 86_400 { return "\(seconds / 3600)h" }
        return "\(seconds / 86_400)d"
    }
}
