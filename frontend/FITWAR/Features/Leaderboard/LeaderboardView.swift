import SwiftUI

/// The `leaderboard` screen. Renders server-ranked standings — it never sorts or
/// re-ranks locally, because rank is the server's answer (Architecture §3.2).
struct LeaderboardView: View {
    @State var viewModel: LeaderboardViewModel

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(FWColor.background)
            .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loading:
            LoadingView(label: "Loading standings…")
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel.load() } })
        case .unauthorized:
            UnauthorizedView(onLogIn: {})
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Couldn't load standings",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel.load() } }
            )
        case .loaded(let board):
            loaded(board)
        }
    }

    @ViewBuilder
    private func loaded(_ board: Leaderboard) -> some View {
        if board.entries.isEmpty {
            GenericStateView(
                symbol: "trophy",
                title: "No standings yet",
                message: "Once someone completes a day, the leaderboard fills in."
            )
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: FWSpacing.lg) {
                    SectionHeader(
                        eyebrow: board.isFinal ? "FINAL STANDINGS" : "LEADERBOARD",
                        title: board.isFinal ? "Final result" : "Standings",
                        subtitle: nil
                    )

                    VStack(spacing: 0) {
                        ForEach(board.entries) { entry in
                            LeaderboardRow(
                                rank: "\(entry.rank)",
                                name: entry.displayName,
                                subLabel: LeaderboardRowPresentation.subLabel(
                                    for: entry, isFinal: board.isFinal
                                ),
                                score: FWNumber.compact(entry.score),
                                isMe: entry.isMe,
                                nameColor: entry.status == .eliminated
                                    ? FWColor.textDim2
                                    : FWColor.textPrimary
                            )
                            if entry.id != board.entries.last?.id {
                                Divider().overlay(FWColor.line)
                            }
                        }
                    }
                    .padding(.vertical, FWSpacing.xs)
                    .background(FWColor.surface)
                    .overlay(
                        RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                            .strokeBorder(FWColor.line)
                    )
                    .clipShape(
                        RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                    )
                }
                .padding(.horizontal, FWSpacing.screenHorizontal)
                .padding(.vertical, FWSpacing.xl)
            }
        }
    }
}
