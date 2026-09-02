import SwiftUI

/// Challenge Detail — the prototype's `detail` screen: circular hero ring, name and
/// "DAY 6 / 30 · MISS TWICE → ELIMINATED" meta, primary CTA, participant list.
///
/// The ring shows challenge-day progress, not a step count. The design's `8,742` is a
/// verified daily metric, and Phase 3 has none — showing today's number would mean
/// inventing it. The pending state is stated plainly instead.
struct ChallengeDetailView: View {
    let challengeId: UUID

    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.challengesService) private var challengesService
    @Environment(\.dismiss) private var dismiss

    @State private var viewModel: ChallengeDetailViewModel?

    var body: some View {
        content
            .background(FWColor.background)
            .task {
                if viewModel == nil {
                    viewModel = ChallengeDetailViewModel(
                        challengeId: challengeId,
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
            LoadingView(label: "Loading challenge…")
        case .loaded(let loaded):
            detail(loaded)
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel?.load() } })
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Challenge unavailable",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel?.load() } },
                secondaryActionTitle: "Back",
                secondaryAction: { dismiss() }
            )
        case .unauthorized:
            UnauthorizedView(onLogIn: { viewModel?.acknowledgeUnauthorized() })
        }
    }

    private func detail(_ loaded: ChallengeDetailViewModel.Content) -> some View {
        let challenge = loaded.challenge

        return ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl - 2) {
                topBar(challenge)

                VStack(alignment: .leading, spacing: FWSpacing.xs) {
                    Text(challenge.name)
                        .font(FWTypography.displayMedium)
                        .foregroundStyle(FWColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(challenge.headerMeta)
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                }
                .padding(.horizontal, FWSpacing.screenHorizontal)

                hero(challenge, progress: loaded.todayProgress)

                actions(challenge)

                if let error = viewModel?.actionError {
                    Text(error)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .padding(.horizontal, FWSpacing.screenHorizontal)
                        .accessibilityLabel("Error: \(error)")
                }

                participants(challenge)
            }
            .padding(.top, 60)
            .padding(.bottom, FWSpacing.xxl)
        }
        .refreshable { await viewModel?.reload() }
    }

    private func topBar(_ challenge: ChallengeDetail) -> some View {
        HStack {
            CircleIconButton(systemName: "chevron.left", accessibilityLabel: "Back") {
                dismiss()
            }
            Spacer()
            Text(challenge.modeMeta)
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)
            Spacer()
            // Balances the back button so the meta label stays optically centered,
            // matching the prototype's back/meta/overflow row.
            Color.clear.frame(width: 34, height: 34)
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    private func hero(_ challenge: ChallengeDetail, progress: DailyProgress?) -> some View {
        VStack(spacing: FWSpacing.xs) {
            ZStack {
                FWProgressRing(progress: scheduleProgress(challenge), size: 206)

                VStack(spacing: 2) {
                    Text(FWNumber.compact(challenge.targetValue))
                        .font(FWFontFamily.archivo(46, .extrabold, relativeTo: .largeTitle))
                        .foregroundStyle(FWColor.textPrimary)
                        .minimumScaleFactor(0.6)
                        .lineLimit(1)

                    Text("DAILY \(challenge.unit.uppercased())")
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)

                    Text(statusLine(challenge, progress: progress))
                        .font(FWTypography.numericSmall)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(statusColor(challenge, progress: progress))
                        .padding(.top, FWSpacing.sm)
                }
                .padding(.horizontal, FWSpacing.xxl)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Daily target")
            .accessibilityValue(
                "\(challenge.targetLabel). \(statusLine(challenge, progress: progress))"
            )

            Text("VERIFIED VIA \(challenge.verificationMethod.displayName)")
                .font(FWTypography.metaLabel)
                .tracking(FWTracking.metaLabel)
                .foregroundStyle(FWColor.textDim2)
                .padding(.top, FWSpacing.xxs)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    /// How far through the challenge's schedule we are. Explicitly a *schedule* ring,
    /// labelled as such — not a metric ring filled from data that doesn't exist yet.
    private func scheduleProgress(_ challenge: ChallengeDetail) -> Double {
        guard challenge.durationDays > 0 else { return 0 }
        return min(1, max(0, Double(challenge.dayIndex) / Double(challenge.durationDays)))
    }

    private func statusLine(_ challenge: ChallengeDetail, progress: DailyProgress?) -> String {
        switch challenge.status {
        case .draft: return "STARTS \(Self.dayFormatter.string(from: challenge.startAt).uppercased())"
        case .completed: return "CHALLENGE COMPLETE"
        case .cancelled: return "CANCELLED"
        case .active:
            guard let progress else { return "JOIN TO TAKE PART" }
            switch progress.status {
            case .pending: return "AWAITING VERIFICATION"
            case .completed: return "TODAY COMPLETE"
            case .missed: return "TODAY MISSED"
            case .excused: return "TODAY EXCUSED"
            }
        }
    }

    private func statusColor(_ challenge: ChallengeDetail, progress: DailyProgress?) -> Color {
        guard challenge.status == .active, let progress else { return FWColor.textDim2 }
        switch progress.status {
        case .completed: return FWColor.accent
        case .missed: return FWColor.red
        case .pending, .excused: return FWColor.orange
        }
    }

    @ViewBuilder
    private func actions(_ challenge: ChallengeDetail) -> some View {
        VStack(spacing: FWSpacing.sm + 2) {
            if challenge.isJoinable {
                FITWARPrimaryButton(
                    title: "JOIN THIS WAR",
                    isLoading: viewModel?.isMutating ?? false
                ) {
                    Task { await viewModel?.join() }
                }
            } else if challenge.myStatus == .active, challenge.status == .active {
                // Verification is Phase 4. A disabled "OPEN TODAY'S MISSION" that leads
                // nowhere would be a broken promise, so the state is named instead —
                // in the design's own hint-box treatment rather than as loose text.
                Text("You're in. Daily verification arrives with the Health phase.")
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textDim)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(FWSpacing.lg)
                    .overlay(
                        RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous)
                            .strokeBorder(FWColor.line)
                    )
            }

            if challenge.isLeavable {
                FITWARSecondaryButton(
                    title: "LEAVE CHALLENGE",
                    isDisabled: viewModel?.isMutating ?? false
                ) {
                    Task { await viewModel?.leave() }
                }
            }

            if challenge.myStatus == .left {
                Text("You left this challenge.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim2)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    private func participants(_ challenge: ChallengeDetail) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            HStack {
                Text("PARTICIPANTS")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow)
                    .foregroundStyle(FWColor.textDim2)
                Spacer()
                if let limit = challenge.participantLimit {
                    Text("\(challenge.participantCount)/\(limit)")
                        .font(FWTypography.numericSmall)
                        .foregroundStyle(FWColor.textDim)
                }
            }

            // Deliberately not a leaderboard: scores are all zero until verification
            // exists, so ranking them would present an order that means nothing.
            ForEach(challenge.participants) { participant in
                RosterRow(
                    displayName: participant.displayName,
                    stateLabel: participant.status.displayName,
                    trailingLabel: participant.userId == challenge.creatorId ? "CREATOR" : "",
                    isMe: viewModel?.isMe(participant.userId) ?? false,
                    stateColor: stateColor(participant.status)
                )
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
    }

    private func stateColor(_ status: ParticipantStatus) -> Color {
        switch status {
        case .active: FWColor.textDim2
        case .completed: FWColor.accent
        case .left: FWColor.textDim2
        case .eliminated: FWColor.red
        }
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "d MMM"
        return formatter
    }()
}
