import SwiftUI

/// One leaderboard/roster row. Presentational only (Leaderboard is a later phase) —
/// see `ChallengeCard`'s note; built now to complete the design-system vocabulary.
struct LeaderboardRow: View {
    let rank: String
    let name: String
    let subLabel: String
    let score: String
    var isMe: Bool = false
    var nameColor: Color = FWColor.textPrimary

    var body: some View {
        HStack(spacing: FWSpacing.md + 1) {
            Text(rank)
                .font(FWTypography.numericMedium)
                .foregroundStyle(isMe ? FWColor.accent : FWColor.textDim2)
                .frame(width: 24, alignment: .leading)

            AvatarView(size: isMe ? 34 : 32)

            VStack(alignment: .leading, spacing: 3) {
                Text(name)
                    .font(isMe ? FWTypography.titleSmall : FWTypography.bodyMedium)
                    .foregroundStyle(nameColor)
                Text(subLabel)
                    .font(FWTypography.metaLabel)
                    .foregroundStyle(FWColor.textDim2)
            }

            Spacer()

            Text(score)
                .font(FWTypography.numericMedium)
                .foregroundStyle(isMe ? FWColor.textPrimary : FWColor.textDim)
        }
        .padding(FWSpacing.md + 1)
        .background(isMe ? FWColor.surface : .clear)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous)
                .strokeBorder(isMe ? FWColor.accent : .clear)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Rank \(rank), \(name), \(subLabel), score \(score)")
    }
}
