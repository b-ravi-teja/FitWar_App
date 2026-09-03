import SwiftUI

/// The live battle screen and the Victory / Defeat screens it resolves into
/// (design screens 19, 20, 29).
///
/// Every branch below renders a phase the view model read from the server. There is no
/// score comparison anywhere in this file — Victory appears because the server said
/// `my_outcome = won`, and for no other reason.
struct BattleDetailView: View {
    let battleId: UUID

    @Environment(\.battlesService) private var battlesService
    @Environment(\.healthKitService) private var healthKitService
    @Environment(\.realtimeClient) private var realtimeClient
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.dismiss) private var dismiss

    @State private var viewModel: BattleDetailViewModel?

    var body: some View {
        Group {
            if let viewModel {
                content(viewModel)
            } else {
                LoadingView(label: "Loading battle…")
            }
        }
        .background(FWColor.background)
        .navigationTitle("Battle")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel == nil {
                viewModel = BattleDetailViewModel(
                    battleId: battleId,
                    battles: battlesService,
                    health: healthKitService,
                    realtime: realtimeClient,
                    sessionManager: sessionManager
                )
            }
            await viewModel?.load()
            viewModel?.connectRealtime()
        }
        .onDisappear { viewModel?.disconnectRealtime() }
    }

    @ViewBuilder
    private func content(_ viewModel: BattleDetailViewModel) -> some View {
        switch viewModel.phase {
        case .loading:
            LoadingView(label: "Loading battle…")

        case .networkFailure:
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

        case .invited(let battle):
            invited(battle, viewModel)

        case .awaitingOpponent(let battle):
            awaiting(battle, viewModel)

        case .active(let battle, let mineIsDone):
            active(battle, mineIsDone: mineIsDone, viewModel)

        case .victory(let battle):
            BattleOutcomeView(battle: battle, didWin: true) { dismiss() }

        case .defeat(let battle):
            BattleOutcomeView(battle: battle, didWin: false) { dismiss() }

        case .cancelled(let battle):
            GenericStateView(
                symbol: "xmark.circle",
                title: "Battle cancelled",
                message: battle.me?.status == .declined
                    ? "You declined this battle. Nothing was recorded."
                    : "\(battle.opponent?.displayName ?? "Your opponent") declined. "
                        + "Nothing was recorded — challenge someone else.",
                primaryActionTitle: "BACK",
                primaryAction: { dismiss() }
            )
        }
    }

    // MARK: - Phases

    private func invited(_ battle: Battle, _ viewModel: BattleDetailViewModel) -> some View {
        page(battle, viewModel) {
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(
                    title: "\(battle.opponent?.displayName ?? "Someone") challenged you",
                    detail: "\(FWNumber.compact(battle.targetValue)) "
                        + "\(battle.unit) a day for \(battle.durationDays) "
                        + "day\(battle.durationDays == 1 ? "" : "s"). Highest total wins."
                )
                FITWARPrimaryButton(title: "ACCEPT") {
                    Task { await viewModel.accept() }
                }
                FITWARSecondaryButton(title: "DECLINE") {
                    Task { await viewModel.decline() }
                }
            }
            .disabled(viewModel.isSubmitting)
        }
    }

    private func awaiting(_ battle: Battle, _ viewModel: BattleDetailViewModel) -> some View {
        page(battle, viewModel) {
            statusBlock(
                title: "Waiting for \(battle.opponent?.displayName ?? "your opponent")",
                detail: "The battle starts the moment they accept. Nothing counts "
                    + "until then."
            )
        }
    }

    private func active(
        _ battle: Battle, mineIsDone: Bool, _ viewModel: BattleDetailViewModel
    ) -> some View {
        page(battle, viewModel) {
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                if mineIsDone {
                    statusBlock(
                        title: "Today's banked",
                        detail: "You've hit today's target. The battle resolves when "
                            + "every day is settled."
                    )
                } else {
                    FITWARPrimaryButton(title: "LOG TODAY") {
                        Task { await viewModel.submitTodaysEvidence() }
                    }
                    .disabled(viewModel.isSubmitting)
                }

                statusBlock(
                    title: "Opponent",
                    detail: "\(battle.opponent?.displayName ?? "Opponent") has banked "
                        + "\(battle.opponent?.daysCompleted ?? 0) of "
                        + "\(battle.durationDays) day\(battle.durationDays == 1 ? "" : "s")."
                )
            }
        }
    }

    // MARK: - Shared chrome

    private func page(
        _ battle: Battle,
        _ viewModel: BattleDetailViewModel,
        @ViewBuilder body: () -> some View
    ) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                header(battle, viewModel)
                if let error = viewModel.actionError {
                    Text(error)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
                body()
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .refreshable { await viewModel.reload() }
    }

    private func header(_ battle: Battle, _ viewModel: BattleDetailViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            HStack {
                Text("DAY \(battle.dayIndex) / \(battle.durationDays)")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow)
                    .foregroundStyle(FWColor.textDim2)
                Spacer()
                if battle.status == .active {
                    // Shown only while a socket is actually attached, so the dot is a
                    // fact rather than decoration.
                    if viewModel.isLive {
                        StatusBadge(text: "LIVE", tone: .accent)
                    }
                    BattleCountdown(seconds: battle.timeRemainingSeconds)
                }
            }

            Text("YOU vs \(battle.opponent?.displayName.uppercased() ?? "OPPONENT")")
                .font(FWTypography.titleMedium)
                .foregroundStyle(FWColor.textPrimary)

            if let me = battle.me, let opponent = battle.opponent {
                BattleVersusBar(
                    myScore: me.score,
                    theirScore: opponent.score,
                    myShare: battle.myShareOfScore
                )
            }
        }
    }

    private func statusBlock(title: String, detail: String?) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xs) {
            Text(title)
                .font(FWTypography.bodyMedium)
                .foregroundStyle(FWColor.textPrimary)
            if let detail {
                Text(detail)
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}
