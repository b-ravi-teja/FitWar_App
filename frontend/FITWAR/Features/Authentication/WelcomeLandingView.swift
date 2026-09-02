import SwiftUI

/// Onboarding step 1 from `FITWAR.dc.html` (`ob1`), copy reproduced verbatim.
/// Positioned as the pre-auth landing screen rather than repeated after sign-up —
/// showing "GET STARTED"/"I already have an account" again right after registering
/// would be redundant, so this is the entry point into `AuthFlowView`, and the
/// post-registration `OnboardingFlowView` covers `ob2`–`ob4` only. Content and
/// visuals are unchanged from the prototype; only where it sits in the flow moved.
struct WelcomeLandingView: View {
    var onGetStarted: () -> Void
    var onLogin: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                Text("FITWAR")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow * 1.5)
                    .foregroundStyle(FWColor.accent)

                Text("Fitness was never supposed to be boring.")
                    .font(FWTypography.heroHeadline)
                    .foregroundStyle(FWColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Challenge your friends. Compete. Stay accountable.")
                    .font(FWTypography.body)
                    .foregroundStyle(FWColor.textDim)
                    .frame(maxWidth: 280, alignment: .leading)
            }
            .padding(.top, 120)

            Spacer()

            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                Rectangle().fill(FWColor.line).frame(height: 1)

                HStack(spacing: FWSpacing.xxl) {
                    statColumn(value: "12.4k", label: "ACTIVE WARS")
                    statColumn(value: "61%", label: "SURVIVAL RATE")
                }

                FITWARPrimaryButton(title: "GET STARTED", action: onGetStarted)
                    .padding(.top, FWSpacing.xxs)

                FITWARTextButton(title: "I already have an account", action: onLogin)
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal + 8)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
    }

    private func statColumn(value: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(value).font(FWTypography.titleLarge).foregroundStyle(FWColor.textPrimary)
            Text(label)
                .font(FWTypography.metaLabel)
                .tracking(FWTracking.metaLabel)
                .foregroundStyle(FWColor.textDim2)
        }
        .accessibilityElement(children: .combine)
    }
}
