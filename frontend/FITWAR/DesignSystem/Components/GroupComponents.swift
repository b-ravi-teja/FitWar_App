import SwiftUI

/// Groups List row. Same card shape as the design's challenge card
/// (`border:1px solid var(--line);background:var(--srf);border-radius:20px;padding:18px`)
/// carrying the group header's own content: name + "8 MEMBERS · 3 ACTIVE CHALLENGES".
struct GroupCard: View {
    let name: String
    let meta: String
    let memberCount: Int

    var body: some View {
        HStack(alignment: .top, spacing: FWSpacing.md) {
            VStack(alignment: .leading, spacing: FWSpacing.xs) {
                Text(name)
                    .font(FWTypography.titleMedium)
                    .foregroundStyle(FWColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(meta)
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.textDim2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            AvatarStack(count: min(memberCount, 4), size: 28)
                .padding(.top, FWSpacing.xxs)
        }
        .padding(FWSpacing.lg + 2)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous))
    }
}

/// Roster row — avatar, name, state sub-label, trailing marker. Matches the design's
/// member row (`padding:13px;border-radius:16px;border:1px solid var(--line)`).
struct RosterRow: View {
    let displayName: String
    let stateLabel: String
    let trailingLabel: String
    var isMe: Bool = false
    var stateColor: Color = FWColor.textDim2

    var body: some View {
        HStack(spacing: FWSpacing.md + 1) {
            AvatarView(size: 38, initials: String(displayName.prefix(1)).uppercased())

            VStack(alignment: .leading, spacing: FWSpacing.xxs) {
                Text(isMe ? "\(displayName) (you)" : displayName)
                    .font(FWTypography.titleSmall)
                    .foregroundStyle(isMe ? FWColor.accent : FWColor.textPrimary)

                Text(stateLabel)
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(stateColor)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // The design's trailing slot holds a short rank glyph ("#1") at display
            // weight. The words that go there instead (a role, "CREATOR") need the
            // quieter tracked-mono meta treatment, or they out-shout the member's name.
            Text(trailingLabel)
                .font(FWTypography.metaLabel)
                .tracking(FWTracking.metaLabel)
                .foregroundStyle(FWColor.textDim2)
        }
        .padding(FWSpacing.md + 1)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// The design's JOIN CODE card — centered mono code in accent, on a surface card.
struct JoinCodeCard: View {
    let code: String
    var onShare: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: FWSpacing.sm) {
            Text("JOIN CODE")
                .font(FWTypography.metaLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)

            Text(code)
                .font(FWFontFamily.mono(34, .bold, relativeTo: .largeTitle))
                .tracking(4)
                .foregroundStyle(FWColor.accent)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, FWSpacing.xxl - 2)
        .padding(.horizontal, FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        .accessibilityElement(children: .ignore)
        // Read the code character by character — VoiceOver otherwise pronounces "K7-XR9"
        // as a word, which is useless for a code someone has to relay out loud.
        .accessibilityLabel("Join code")
        .accessibilityValue(code.map(String.init).joined(separator: " "))
    }
}

/// The circular back/overflow button used on every nav-less screen in the design
/// (`width:34px;height:34px;border-radius:99px;border:1px solid var(--line)`).
struct CircleIconButton: View {
    let systemName: String
    let accessibilityLabel: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(FWColor.textPrimary)
                .frame(width: 34, height: 34)
                .background(FWColor.surface)
                .overlay(Circle().strokeBorder(FWColor.line))
                .clipShape(Circle())
        }
        .buttonStyle(FWPressableStyle())
        .accessibilityLabel(accessibilityLabel)
    }
}
