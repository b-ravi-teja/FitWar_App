import SwiftUI

/// `ob4` from the prototype — "Create your fighter". Username is pre-filled from
/// registration's `displayName` (editable here) since that's the same field, not a
/// second collection of the same data; fitness level is genuinely new but has no
/// backend column yet (Architecture's frozen ERD has none) — see
/// `OnboardingViewModel`'s doc comment for why it stays local-only in Phase 2.
struct OnboardingProfileView: View {
    var viewModel: OnboardingViewModel
    var onFinished: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(eyebrow: "STEP 3/3", title: "Create your fighter")

            HStack(spacing: FWSpacing.lg) {
                RoundedRectangle(cornerRadius: FWRadius.large - 4, style: .continuous)
                    .strokeBorder(FWColor.line2, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                    .frame(width: 78, height: 78)
                    .overlay(
                        Text("ADD\nPHOTO")
                            .font(FWTypography.metaLabel)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(FWColor.textDim2)
                    )
                    .accessibilityLabel("Add profile photo — not yet available")

                FWTextField(label: "Username", text: Binding(get: { viewModel.displayName }, set: { viewModel.displayName = $0 }), textContentType: .name)
            }

            VStack(alignment: .leading, spacing: FWSpacing.sm + 2) {
                Text("FITNESS LEVEL")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.textDim2)

                HStack(spacing: FWSpacing.sm) {
                    ForEach(viewModel.fitnessLevels, id: \.self) { level in
                        let isSelected = viewModel.fitnessLevel == level
                        Button {
                            viewModel.fitnessLevel = level
                        } label: {
                            Text(level)
                                .font(FWTypography.bodyMedium)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, FWSpacing.md + 2)
                                .foregroundStyle(FWColor.textPrimary)
                                .background(isSelected ? FWColor.surface2 : FWColor.surface)
                                .overlay(
                                    RoundedRectangle(cornerRadius: FWRadius.small + 4, style: .continuous)
                                        .strokeBorder(isSelected ? FWColor.line2 : FWColor.line)
                                )
                                .clipShape(RoundedRectangle(cornerRadius: FWRadius.small + 4, style: .continuous))
                        }
                        .buttonStyle(FWPressableStyle())
                        .accessibilityAddTraits(isSelected ? .isSelected : [])
                    }
                }
            }

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage).font(FWTypography.bodySmall).foregroundStyle(FWColor.red)
            }

            Spacer()

            FITWARPrimaryButton(
                title: "ENTER FITWAR",
                isLoading: viewModel.isSubmitting,
                isDisabled: !viewModel.canFinish,
                action: {
                    Task {
                        if await viewModel.finish() { onFinished() }
                    }
                }
            )
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, 80)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
    }
}
