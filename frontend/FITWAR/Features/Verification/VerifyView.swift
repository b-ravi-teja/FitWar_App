import SwiftUI

/// `verify` from the prototype — Today's Mission. Renders whichever state the view
/// model is in; it holds no HealthKit import and makes no completion decision of its own.
struct VerifyView: View {
    @State var viewModel: VerifyViewModel
    var onCompleted: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(
                eyebrow: "TODAY'S MISSION",
                title: viewModel.challengeName,
                subtitle: nil
            )

            content

            Spacer()
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, FWSpacing.xl)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
        .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loadingDay:
            statusBlock(title: "Loading today's mission…", detail: nil)

        case .healthUnavailable:
            // Product-level copy — never a raw framework error string.
            statusBlock(
                title: "Apple Health isn't available",
                detail: "This device can't provide health data, so this challenge can't be "
                    + "verified automatically here."
            )

        case .notConnected:
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(
                    title: "Connect Apple Health",
                    detail: "We read only \(viewModel.activity.displayName.lowercased()) for this "
                        + "challenge — nothing else."
                )
                FITWARPrimaryButton(title: "CONNECT APPLE HEALTH") {
                    Task { await viewModel.connectHealth() }
                }
            }

        case .requestingPermission:
            statusBlock(title: "Waiting for permission…", detail: nil)

        case .noActivityFound(let day):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                targetBlock(day)
                statusBlock(
                    title: "No activity recorded yet",
                    detail: "We read nothing for today. Either there's no "
                        + "\(viewModel.activity.displayName.lowercased()) recorded yet, or health "
                        + "access is off — iOS doesn't tell apps which. Check Settings › Privacy "
                        + "& Security › Health › FITWAR if that looks wrong."
                )
                FITWARSecondaryButton(title: "OPEN SETTINGS") { openSettings() }
                FITWARSecondaryButton(title: "SYNC AGAIN") { Task { await viewModel.sync() } }
            }

        case .readyToSync(let day):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                targetBlock(day)
                FITWARPrimaryButton(title: "SYNC NOW") { Task { await viewModel.sync() } }
            }

        case .fetchingEvidence(let day):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                targetBlock(day)
                statusBlock(title: "Reading your activity…", detail: nil)
            }

        case .submitting(let day):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                targetBlock(day)
                statusBlock(title: "Verifying…", detail: nil)
            }

        case .verified(let response):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(
                    title: response.idempotentReplay ? "Already complete" : "Mission complete",
                    detail: "\(FWNumber.compact(response.verification.value)) recorded against a "
                        + "target of \(FWNumber.compact(response.verification.target))."
                )
                if let resolution = response.resolution {
                    xpBreakdown(resolution)
                }
                FITWARPrimaryButton(title: "DONE", action: onCompleted)
            }

        case .insufficient(let day, let record):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                targetBlock(day)
                statusBlock(
                    title: "Not there yet",
                    detail: VerificationReasonPresentation.message(for: record, unit: day.unit)
                )
                FITWARSecondaryButton(title: "SYNC AGAIN") { Task { await viewModel.sync() } }
            }

        case .rejected(let message):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(title: "Couldn't verify that", detail: message)
                FITWARSecondaryButton(title: "TRY AGAIN") { Task { await viewModel.load() } }
            }

        case .networkFailure:
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(
                    title: "No connection",
                    detail: "Your activity wasn't submitted. It'll still count once you're back "
                        + "online and sync again."
                )
                FITWARSecondaryButton(title: "RETRY") { Task { await viewModel.sync() } }
            }

        case .serverError(let message):
            VStack(alignment: .leading, spacing: FWSpacing.lg) {
                statusBlock(title: "Something went wrong", detail: message)
                FITWARSecondaryButton(title: "RETRY") { Task { await viewModel.load() } }
            }
        }
    }

    /// The design's "XP awarded, broken into components" — every number server-computed.
    private func xpBreakdown(_ resolution: DayResolution) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xs) {
            HStack {
                Text("XP EARNED")
                    .font(FWTypography.eyebrowLabel)
                    .foregroundStyle(FWColor.textDim2)
                Spacer()
                Text("+\(resolution.xpAwarded)")
                    .font(FWTypography.numericLarge)
                    .foregroundStyle(FWColor.accent)
            }
            componentRow("Mission complete", resolution.completionXP)
            if resolution.streakBonusXP > 0 {
                componentRow("Streak bonus", resolution.streakBonusXP)
            }
            componentRow("Day streak", resolution.currentStreak, isXP: false)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
    }

    private func componentRow(_ label: String, _ value: Int, isXP: Bool = true) -> some View {
        HStack {
            Text(label).font(FWTypography.bodySmall).foregroundStyle(FWColor.textDim)
            Spacer()
            Text(isXP ? "+\(value)" : "\(value)")
                .font(FWTypography.numericSmall)
                .foregroundStyle(FWColor.textPrimary)
        }
        .accessibilityElement(children: .combine)
    }

    private func targetBlock(_ day: DailyProgress) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xs) {
            Text("DAY \(day.dayIndex) TARGET")
                .font(FWTypography.eyebrowLabel)
                .foregroundStyle(FWColor.textDim2)
            Text("\(FWNumber.compact(day.target)) \(day.unit.uppercased())")
                .font(FWTypography.numericLarge)
                .foregroundStyle(FWColor.textPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
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
        .accessibilityElement(children: .combine)
    }

    private func openSettings() {
        #if canImport(UIKit)
            // iOS allows deep-linking to the app's own settings page only; there is no
            // public URL for the Health data-access screen itself.
            if let url = URL(string: UIApplication.openSettingsURLString) {
                UIApplication.shared.open(url)
            }
        #endif
    }
}

#if canImport(UIKit)
    import UIKit
#endif
