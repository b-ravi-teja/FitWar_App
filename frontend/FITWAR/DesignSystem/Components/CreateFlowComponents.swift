import SwiftUI

/// The Create-flow step indicator: five thin segments filled up to the current step
/// (`flex:1;height:3px;border-radius:99px`), with a "3/5" label alongside.
struct StepProgressIndicator: View {
    let currentStep: Int
    let totalSteps: Int

    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<totalSteps, id: \.self) { index in
                Capsule()
                    .fill(index <= currentStep ? FWColor.accent : FWColor.surface2)
                    .frame(height: 3)
            }
        }
        .animation(FWAnimation.progressFill, value: currentStep)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(currentStep + 1) of \(totalSteps)")
    }
}

/// Two-column grid select card (activity picker) — icon swatch above a label,
/// accent border when chosen (`style-hover="border-color:var(--acc)"` in the prototype,
/// rendered here as a real selected state since touch has no hover).
struct GridSelectCard: View {
    let title: String
    let systemImage: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: FWSpacing.xl) {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(isSelected ? FWColor.accent.opacity(0.18) : FWColor.surface2)
                    .frame(width: 22, height: 22)
                    .overlay(
                        Image(systemName: systemImage)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(isSelected ? FWColor.accent : FWColor.textDim)
                    )

                Text(title)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textPrimary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(FWSpacing.lg)
            .background(FWColor.surface)
            .overlay(
                RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous)
                    .strokeBorder(isSelected ? FWColor.accent : FWColor.line)
            )
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous))
        }
        .buttonStyle(FWPressableStyle())
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }
}

/// Full-width game-mode card: name + tag on one line, description beneath.
struct ModeSelectCard: View {
    let name: String
    let tag: String
    let blurb: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: FWSpacing.sm) {
                HStack {
                    Text(name)
                        .font(FWTypography.titleMedium)
                        .foregroundStyle(FWColor.textPrimary)
                    Spacer()
                    Text(tag)
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                }
                Text(blurb)
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(FWSpacing.lg + 2)
            .background(FWColor.surface)
            .overlay(
                RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                    .strokeBorder(isSelected ? FWColor.accent : FWColor.line)
            )
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        }
        .buttonStyle(FWPressableStyle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }
}

/// The dashed "SOON" chip row for modes the design shows but V1 doesn't build.
struct ComingSoonChip: View {
    let name: String

    var body: some View {
        Text("\(name) · SOON")
            .font(FWTypography.metaLabel)
            .tracking(FWTracking.metaLabel)
            .foregroundStyle(FWColor.textDim2)
            .padding(.horizontal, FWSpacing.sm + 2)
            .padding(.vertical, FWSpacing.xs + 1)
            .overlay(
                Capsule().strokeBorder(
                    FWColor.line2, style: StrokeStyle(lineWidth: 1, dash: [3, 3])
                )
            )
            .accessibilityLabel("\(name), coming soon")
    }
}

/// A label/value row on a hairline divider — the rules summary list, and the
/// review card's detail lines.
struct RuleRow: View {
    let label: String
    let value: String
    var showsDivider: Bool = true

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(label)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textDim)
                Spacer()
                Text(value)
                    .font(FWTypography.numericMedium)
                    .foregroundStyle(FWColor.textPrimary)
            }
            .padding(.vertical, FWSpacing.md + 3)

            if showsDivider {
                Rectangle().fill(FWColor.line).frame(height: 1)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// The failure-rule callout on the rules step: orange dot for WARNING, red for OUT.
struct FailureRuleCallout: View {
    let lines: [(color: Color, text: String)]

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.sm) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                HStack(spacing: FWSpacing.sm + 2) {
                    Circle().fill(line.color).frame(width: 7, height: 7)
                    Text(line.text)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.textDim)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium + 2, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// A filled or outlined pill used on the review card's tag row.
struct TagPill: View {
    let text: String
    var isFilled: Bool = false

    var body: some View {
        Text(text)
            .font(FWTypography.metaLabel)
            .tracking(FWTracking.metaLabel)
            .foregroundStyle(isFilled ? FWColor.onAccent : FWColor.textDim)
            .padding(.horizontal, FWSpacing.sm + 2)
            .padding(.vertical, FWSpacing.xs + 1)
            .background(isFilled ? FWColor.accent : .clear)
            .overlay(Capsule().strokeBorder(isFilled ? .clear : FWColor.line))
            .clipShape(Capsule())
    }
}
