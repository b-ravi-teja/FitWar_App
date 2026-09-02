import SwiftUI

/// Home/Challenges list card. Presentational only — Phase 2 has no Challenge data
/// model yet (Challenges are a later phase), so this takes plain values and is not
/// wired to any live screen; it exists now so the design-system vocabulary is
/// complete and ready for the Challenges phase to consume directly.
struct ChallengeCard: View {
    let name: String
    let meta: String
    let statusText: String
    let statusTone: StatusBadge.Tone
    let progressLabel: String
    let rankLabel: String
    let progress: Double

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.lg) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: FWSpacing.xxs) {
                    Text(name)
                        .font(FWTypography.titleMedium)
                        .foregroundStyle(FWColor.textPrimary)
                    Text(meta)
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                }
                Spacer()
                StatusBadge(text: statusText, tone: statusTone)
            }

            HStack(alignment: .lastTextBaseline) {
                Text(progressLabel)
                    .font(FWTypography.titleLarge)
                    .foregroundStyle(FWColor.textPrimary)
                Spacer()
                Text(rankLabel)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textDim)
            }

            FWProgressBar(progress: progress, height: 4)
        }
        .padding(FWSpacing.xl)
        .background(FWColor.surface)
        .overlay(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous).strokeBorder(FWColor.line))
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}
