import SwiftUI

/// `ob3` from the prototype, now wired to the real Phase 4 `HealthKitService`.
///
/// The Health Connect button is gone. It is the Android provider, never implemented on
/// iOS (Architecture §21), and the prototype only ever wired it to "continue" — shipping
/// a button that cannot do anything is the same mistake §20.8 refused for Sign in with
/// Apple. Apple Health and an honest skip are the two real choices on this platform.
struct OnboardingHealthView: View {
    var viewModel: OnboardingViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(
                eyebrow: "STEP 2/3",
                title: "Connect health data",
                subtitle: viewModel.isHealthAvailable
                    ? "Eligible activity is verified automatically. We read the metric for your active challenge — nothing else."
                    : "This device can't provide health data. You can still compete — those challenges are verified by video proof instead."
            )

            VStack(spacing: 0) {
                permissionRow(label: "Steps & distance", value: "READ")
                Divider().overlay(FWColor.line)
                permissionRow(label: "Workouts & calories", value: "READ")
                Divider().overlay(FWColor.line)
                permissionRow(label: "Everything else", value: "NEVER", dim: true)
            }
            .padding(FWSpacing.lg)
            .background(FWColor.surface)
            .overlay(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous).strokeBorder(FWColor.line))
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))

            Spacer()

            VStack(spacing: FWSpacing.sm + 2) {
                if viewModel.isHealthAvailable {
                    FITWARPrimaryButton(title: "CONNECT APPLE HEALTH") {
                        Task { await viewModel.connectHealth() }
                    }
                    .disabled(viewModel.isSubmitting)
                    FITWARTextButton(title: "Skip for now") {
                        Task { await viewModel.skipHealth() }
                    }
                } else {
                    FITWARPrimaryButton(title: "CONTINUE") {
                        Task { await viewModel.skipHealth() }
                    }
                    .disabled(viewModel.isSubmitting)
                }
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, 80)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
    }

    private func permissionRow(label: String, value: String, dim: Bool = false) -> some View {
        HStack {
            Text(label).font(FWTypography.bodyMedium).foregroundStyle(dim ? FWColor.textDim2 : FWColor.textDim)
            Spacer()
            Text(value)
                .font(FWTypography.numericSmall)
                .foregroundStyle(dim ? FWColor.textDim2 : FWColor.accent)
        }
        .padding(.vertical, FWSpacing.sm)
        .accessibilityElement(children: .combine)
    }
}
