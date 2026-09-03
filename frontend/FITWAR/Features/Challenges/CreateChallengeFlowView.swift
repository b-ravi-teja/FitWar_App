import SwiftUI

/// The design's 5-step create flow, unchanged in shape: circular back button + 5-segment
/// step bar + "3/5" label along the top, one step's content in the middle, one full-width
/// CTA pinned at the bottom. Step 5's "START CHALLENGE" is what actually POSTs.
struct CreateChallengeFlowView: View {
    let group: GroupSummary
    var onCreated: (ChallengeDetail) -> Void
    var onCancel: () -> Void

    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.challengesService) private var challengesService
    @Environment(\.groupsService) private var groupsService

    @State private var viewModel: CreateChallengeViewModel?

    var body: some View {
        Group {
            if let viewModel {
                flow(viewModel)
            } else {
                LoadingView()
            }
        }
        .background(FWColor.background)
        .task {
            if viewModel == nil {
                let model = CreateChallengeViewModel(
                    group: group,
                    challengesService: challengesService,
                    groupsService: groupsService,
                    sessionManager: sessionManager
                )
                model.select(activity: .steps)
                viewModel = model
            }
            await viewModel?.loadJoinCode()
        }
    }

    private func flow(_ viewModel: CreateChallengeViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl - 2) {
            topBar(viewModel)

            ScrollView {
                VStack(alignment: .leading, spacing: FWSpacing.xl) {
                    switch viewModel.step {
                    case .activity: activityStep(viewModel)
                    case .mode: modeStep(viewModel)
                    case .rules: rulesStep(viewModel)
                    case .invite: inviteStep(viewModel)
                    case .review: reviewStep(viewModel)
                    }
                }
                .padding(.bottom, FWSpacing.xl)
            }
            .scrollBounceBehavior(.basedOnSize)

            if let error = viewModel.errorMessage {
                Text(error)
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.red)
                    .accessibilityLabel("Error: \(error)")
            }

            FITWARPrimaryButton(
                title: viewModel.step.ctaTitle,
                isLoading: viewModel.isSubmitting
            ) {
                if viewModel.step == .review {
                    Task {
                        if let created = await viewModel.submit() {
                            onCreated(created)
                        }
                    }
                } else {
                    viewModel.advance()
                }
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, 66)
        .padding(.bottom, FWSpacing.xxl + 2)
        .animation(FWAnimation.entrance, value: viewModel.step)
    }

    private func topBar(_ viewModel: CreateChallengeViewModel) -> some View {
        HStack(spacing: FWSpacing.md) {
            CircleIconButton(
                systemName: "chevron.left",
                accessibilityLabel: viewModel.isFirstStep ? "Cancel" : "Back"
            ) {
                if viewModel.isFirstStep {
                    onCancel()
                } else {
                    viewModel.goBack()
                }
            }

            StepProgressIndicator(
                currentStep: viewModel.step.rawValue,
                totalSteps: CreateChallengeViewModel.Step.allCases.count
            )

            Text("\(viewModel.step.rawValue + 1)/\(CreateChallengeViewModel.Step.allCases.count)")
                .font(FWTypography.eyebrowLabel)
                .foregroundStyle(FWColor.textDim2)
                .accessibilityHidden(true) // the step bar already announces this
        }
    }

    // MARK: Steps

    private func activityStep(_ viewModel: CreateChallengeViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xl) {
            stepTitle("Pick the activity")

            LazyVGrid(
                columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
                spacing: 10
            ) {
                // Only the four activities V1 verifies. The prototype also shows Squats
                // and Duration; those aren't in the frozen activity list, and offering
                // them would create challenges nothing can ever verify.
                ForEach(ActivityType.allCases, id: \.self) { activity in
                    GridSelectCard(
                        title: activity.displayName,
                        systemImage: activity.symbolName,
                        isSelected: viewModel.activity == activity
                    ) {
                        viewModel.select(activity: activity)
                    }
                }
            }
        }
    }

    private func modeStep(_ viewModel: CreateChallengeViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.lg + 2) {
            stepTitle("Choose the game mode")

            ForEach(GameMode.selectable, id: \.self) { mode in
                ModeSelectCard(
                    name: mode.displayName,
                    tag: mode.tag,
                    blurb: mode.blurb,
                    isSelected: viewModel.mode == mode
                ) {
                    viewModel.mode = mode
                }
            }

            HStack(spacing: FWSpacing.sm) {
                ForEach(ComingSoonMode.allCases, id: \.self) { mode in
                    ComingSoonChip(name: mode.rawValue)
                }
            }
            .padding(.top, 2)
        }
    }

    private func rulesStep(_ viewModel: CreateChallengeViewModel) -> some View {
        @Bindable var model = viewModel

        return VStack(alignment: .leading, spacing: FWSpacing.lg) {
            stepTitle("Set the rules")

            FWTextField(label: "Challenge name", text: $model.name, placeholder: viewModel.resolvedName)

            VStack(spacing: 0) {
                ForEach(Array(viewModel.ruleRows.enumerated()), id: \.offset) { index, rule in
                    RuleRow(
                        label: rule.label,
                        value: rule.value,
                        showsDivider: index < viewModel.ruleRows.count - 1
                    )
                }
            }

            stepper(
                label: "Duration",
                value: "\(viewModel.durationDays) days",
                onDecrease: { model.durationDays = max(1, model.durationDays - 7) },
                onIncrease: { model.durationDays = min(365, model.durationDays + 7) }
            )

            stepper(
                label: "Daily target",
                value: viewModel.targetLabel,
                onDecrease: { model.targetValue = max(step(for: model.activity), model.targetValue - step(for: model.activity)) },
                onIncrease: { model.targetValue += step(for: model.activity) }
            )

            Picker("Verification", selection: $model.verification) {
                Text("Health data").tag(VerificationMethod.appleHealth)
                Text("Video proof").tag(VerificationMethod.manualProof)
            }
            .pickerStyle(.segmented)

            FailureRuleCallout(
                lines: viewModel.mode == .survival
                    ? [
                        (FWColor.orange, "Miss once → WARNING"),
                        (FWColor.red, "Miss twice → ELIMINATED"),
                    ]
                    : [(FWColor.accent, "Everyone keeps playing. Highest total wins.")]
            )
        }
    }

    private func inviteStep(_ viewModel: CreateChallengeViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.lg + 2) {
            stepTitle("Invite your squad")

            if viewModel.joinCode.isEmpty {
                LoadingView(label: "Loading join code…")
                    .frame(height: 120)
            } else {
                JoinCodeCard(code: viewModel.joinCode)
            }

            Text(
                "Anyone with this code joins \(viewModel.group.name) and can then join this challenge."
            )
            .font(FWTypography.bodySmall)
            .foregroundStyle(FWColor.textDim)
            .fixedSize(horizontal: false, vertical: true)

            ShareLink(
                item: "Join my FITWAR squad \(viewModel.group.name) with code \(viewModel.joinCode)"
            ) {
                Text("SHARE INVITE")
                    .font(FWTypography.buttonLabel)
                    .tracking(0.6)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 17)
                    .foregroundStyle(FWColor.textPrimary)
                    .background(FWColor.surface2)
                    .overlay(
                        RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous)
                            .strokeBorder(FWColor.line)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous))
            }
            .disabled(viewModel.joinCode.isEmpty)
        }
    }

    private func reviewStep(_ viewModel: CreateChallengeViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.lg + 2) {
            stepTitle("Ready to declare war?")

            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                Text(viewModel.resolvedName)
                    .font(FWTypography.titleLarge)
                    .foregroundStyle(FWColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 7) {
                    TagPill(text: viewModel.mode.displayName, isFilled: true)
                    TagPill(text: viewModel.durationLabel)
                    TagPill(text: viewModel.verification.displayName)
                }

                Rectangle().fill(FWColor.line).frame(height: 1)

                summaryRow("Daily target", viewModel.targetLabel)
                summaryRow("Failure rule", viewModel.failureRuleLabel)
                summaryRow("Squad", viewModel.group.name.uppercased())
            }
            .padding(FWSpacing.xxl - 2)
            .background(FWColor.surface)
            .overlay(
                RoundedRectangle(cornerRadius: FWRadius.large + 2, style: .continuous)
                    .strokeBorder(FWColor.line)
            )
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.large + 2, style: .continuous))
            .shadow(color: .black.opacity(0.18), radius: 20, y: 8)
        }
    }

    // MARK: Pieces

    private func stepTitle(_ text: String) -> some View {
        Text(text)
            .font(FWFontFamily.archivo(28, .extrabold, relativeTo: .title))
            .foregroundStyle(FWColor.textPrimary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func summaryRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(FWTypography.bodySmall)
                .foregroundStyle(FWColor.textDim)
            Spacer()
            Text(value)
                .font(FWTypography.numericSmall)
                .foregroundStyle(FWColor.textPrimary)
        }
        .accessibilityElement(children: .combine)
    }

    private func stepper(
        label: String,
        value: String,
        onDecrease: @escaping () -> Void,
        onIncrease: @escaping () -> Void
    ) -> some View {
        HStack {
            Text(label)
                .font(FWTypography.bodyMedium)
                .foregroundStyle(FWColor.textDim)
            Spacer()
            Text(value)
                .font(FWTypography.numericMedium)
                .foregroundStyle(FWColor.textPrimary)
            Stepper(label, onIncrement: onIncrease, onDecrement: onDecrease)
                .labelsHidden()
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(label)
        .accessibilityValue(value)
    }

    private func step(for activity: ActivityType) -> Int {
        switch activity {
        case .steps: 1_000
        case .activeCalories: 50
        case .distance: 1
        case .pushups: 10
        }
    }
}
