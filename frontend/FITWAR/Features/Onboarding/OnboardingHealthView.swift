import SwiftUI

/// `ob3` from the prototype. Both connect buttons just advance the flow (§15 — no
/// real HealthKit call yet, no fake Health Connect behavior); "Skip for now" does
/// the same thing, matching the prototype's own demo wiring exactly.
struct OnboardingHealthView: View {
    var viewModel: OnboardingViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(
                eyebrow: "STEP 2/3",
                title: "Connect health data",
                subtitle: "Eligible activity is verified automatically. We read the metric for your active challenge — nothing else."
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
                FITWARPrimaryButton(title: "CONNECT APPLE HEALTH") {
                    Task { await viewModel.connectHealth(.appleHealth) }
                }
                FITWARSecondaryButton(title: "CONNECT HEALTH CONNECT") {
                    Task { await viewModel.connectHealth(.healthConnect) }
                }
                FITWARTextButton(title: "Skip for now", action: viewModel.skipHealth)
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
