import SwiftUI

/// Small pill status label (e.g. "VERIFIED", "1 WARNING", "LIVE") — the prototype's
/// recurring `border-radius:99px;padding:6-9px;border:1px solid var(--line)` chip.
struct StatusBadge: View {
    enum Tone {
        case accent, warning, danger, info, gold, neutral

        var color: Color {
            switch self {
            case .accent: FWColor.accent
            case .warning: FWColor.orange
            case .danger: FWColor.red
            case .info: FWColor.blue
            case .gold: FWColor.gold
            case .neutral: FWColor.textDim2
            }
        }
    }

    let text: String
    var tone: Tone = .neutral

    var body: some View {
        Text(text)
            .font(FWTypography.metaLabel)
            .tracking(FWTracking.metaLabel)
            .textCase(.uppercase)
            .foregroundStyle(tone.color)
            .padding(.horizontal, FWSpacing.sm + 2)
            .padding(.vertical, FWSpacing.xs)
            .overlay(
                Capsule().strokeBorder(FWColor.line)
            )
    }
}

/// The day-streak pill (flame + number) shown on Home, Group roster, Profile.
struct StreakBadge: View {
    let days: Int
    var isCompact: Bool = false

    var body: some View {
        HStack(spacing: FWSpacing.xxs) {
            Text("🔥")
            Text("\(days) DAY\(days == 1 ? "" : "S")")
        }
        .font(isCompact ? FWTypography.metaLabel : FWTypography.numericSmall)
        .tracking(FWTracking.metaLabel)
        .foregroundStyle(FWColor.orange)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(days) day streak")
    }
}
