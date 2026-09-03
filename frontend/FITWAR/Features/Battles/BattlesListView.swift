import SwiftUI

/// The BATTLES tab (design screen 19): the live battle, invitations, and history,
/// plus the way into "CHALLENGE SOMEONE".
struct BattlesListView: View {
    @Environment(\.battlesService) private var battlesService
    @Environment(\.groupsService) private var groupsService
    @Environment(SessionManager.self) private var sessionManager

    @State private var viewModel: BattlesListViewModel?
    @State private var isCreating = false
    @State private var selectedBattleId: UUID?

    var body: some View {
        NavigationStack {
            Group {
                if let viewModel {
                    content(viewModel)
                } else {
                    LoadingView(label: "Loading battles…")
                }
            }
            .background(FWColor.background)
            .navigationTitle("Battles")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { isCreating = true } label: {
                        Image(systemName: "plus")
                    }
                    .tint(FWColor.accent)
                    .accessibilityLabel("Challenge someone")
                }
            }
            .navigationDestination(item: $selectedBattleId) { battleId in
                BattleDetailView(battleId: battleId)
            }
            .sheet(isPresented: $isCreating) {
                CreateBattleView { battle in
                    isCreating = false
                    Task {
                        await viewModel?.reload()
                        selectedBattleId = battle.id
                    }
                }
            }
        }
        .task {
            if viewModel == nil {
                viewModel = BattlesListViewModel(
                    battles: battlesService,
                    groups: groupsService,
                    sessionManager: sessionManager
                )
            }
            await viewModel?.load()
        }
    }

    @ViewBuilder
    private func content(_ viewModel: BattlesListViewModel) -> some View {
        switch viewModel.state {
        case .loading:
            LoadingView(label: "Loading battles…")

        case .networkError:
            NetworkErrorView { Task { await viewModel.load() } }

        case .unauthorized:
            UnauthorizedView { Task { await sessionManager.logout() } }

        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel.load() } }
            )

        case .loaded:
            if !viewModel.hasAnything {
                EmptyStateView(
                    title: "No battles yet.",
                    message: "Challenge a squad-mate to a head-to-head and settle it.",
                    actionTitle: "CHALLENGE SOMEONE",
                    action: { isCreating = true }
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                list(viewModel)
            }
        }
    }

    private func list(_ viewModel: BattlesListViewModel) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                if let error = viewModel.actionError {
                    Text(error)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                if !viewModel.invitations.isEmpty {
                    section("INCOMING") {
                        ForEach(viewModel.invitations) { battle in
                            invitationCard(battle, viewModel)
                        }
                    }
                }

                if let live = viewModel.live {
                    section("LIVE BATTLE") {
                        BattleCard(battle: live) { selectedBattleId = live.id }
                    }
                }

                if !viewModel.awaitingOpponent.isEmpty {
                    section("AWAITING OPPONENT") {
                        ForEach(viewModel.awaitingOpponent) { battle in
                            BattleCard(battle: battle) { selectedBattleId = battle.id }
                        }
                    }
                }

                if !viewModel.history.isEmpty {
                    section("HISTORY") {
                        ForEach(viewModel.history) { battle in
                            BattleCard(battle: battle) { selectedBattleId = battle.id }
                        }
                    }
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
        }
        .refreshable { await viewModel.reload() }
    }

    private func invitationCard(
        _ battle: Battle, _ viewModel: BattlesListViewModel
    ) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            BattleCard(battle: battle) { selectedBattleId = battle.id }
            HStack(spacing: FWSpacing.sm) {
                FITWARPrimaryButton(title: "ACCEPT") {
                    Task { await viewModel.accept(battle) }
                }
                FITWARSecondaryButton(title: "DECLINE") {
                    Task { await viewModel.decline(battle) }
                }
            }
            .disabled(viewModel.isSubmitting)
        }
    }

    private func section(
        _ title: String, @ViewBuilder content: () -> some View
    ) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            Text(title)
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)
            content()
        }
    }
}
