import AVKit
import SwiftUI

/// The reviewer's queue for one challenge. Only reachable by an authorized reviewer —
/// the server enforces that, and an unauthorized caller gets 403 rather than an empty list.
struct ProofReviewView: View {
    @State var viewModel: ProofReviewViewModel
    @State private var playing: URL?

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(FWColor.background)
            .task { await viewModel.load() }
            .sheet(isPresented: Binding(get: { playing != nil }, set: { if !$0 { playing = nil } })) {
                if let playing {
                    VideoPlayer(player: AVPlayer(url: playing)).ignoresSafeArea()
                }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loading:
            LoadingView(label: "Loading proof queue…")
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel.load() } })
        case .unauthorized:
            UnauthorizedView(onLogIn: {})
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Couldn't load the queue",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel.load() } }
            )
        case .loaded(let proofs):
            if proofs.isEmpty {
                GenericStateView(
                    symbol: "checkmark.seal",
                    title: "Nothing to review",
                    message: "Submitted proof shows up here for you to approve or reject."
                )
            } else {
                queue(proofs)
            }
        }
    }

    private func queue(_ proofs: [PendingProof]) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                SectionHeader(eyebrow: "PROOF REVIEW", title: "Pending", subtitle: nil)
                if let error = viewModel.lastError {
                    Text(error)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                }
                ForEach(proofs) { proof in
                    card(proof)
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
        }
    }

    private func card(_ proof: PendingProof) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            HStack {
                Text(proof.participantDisplayName)
                    .font(FWTypography.titleSmall)
                    .foregroundStyle(FWColor.textPrimary)
                Spacer()
                Text("\(FWNumber.compact(proof.claimedValue)) / \(FWNumber.compact(proof.target))")
                    .font(FWTypography.numericSmall)
                    .foregroundStyle(FWColor.textDim)
            }

            if proof.mediaAvailable {
                FITWARSecondaryButton(title: "WATCH PROOF") {
                    Task { playing = await viewModel.playbackURL(for: proof) }
                }
            } else {
                // Retention already removed the object — say so rather than offering a
                // player that cannot load.
                Text("Video no longer available.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim2)
            }

            HStack(spacing: FWSpacing.sm) {
                FITWARPrimaryButton(
                    title: "APPROVE",
                    isLoading: viewModel.reviewingId == proof.verificationRecordId
                ) {
                    Task { await viewModel.review(proof, approve: true) }
                }
                FITWARSecondaryButton(
                    title: "REJECT",
                    isDisabled: viewModel.reviewingId != nil
                ) {
                    Task { await viewModel.review(proof, approve: false) }
                }
            }
        }
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
    }
}
