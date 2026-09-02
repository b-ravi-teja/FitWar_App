import SwiftUI

/// The one recurring primary-CTA shape in the whole app: full-width pill, filled
/// accent, bold uppercase-tracked Archivo label (`FITWAR.dc.html`'s ubiquitous
/// `padding:19px;border-radius:16px;background:var(--acc)` button).
struct FITWARPrimaryButton: View {
    let title: String
    var isLoading: Bool = false
    var isDisabled: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Text(title)
                    .font(FWTypography.buttonLabel)
                    .tracking(0.8)
                    .opacity(isLoading ? 0 : 1)

                if isLoading {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .tint(FWColor.onAccent)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 19)
            .foregroundStyle(FWColor.onAccent)
            .background(FWColor.accent.opacity(isDisabled ? 0.4 : 1))
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous))
        }
        .disabled(isDisabled || isLoading)
        .buttonStyle(FWPressableStyle())
        .accessibilityAddTraits(isLoading ? .updatesFrequently : [])
    }
}

/// Secondary CTA: `surface2`-filled, hairline border — the design's recurring
/// non-primary action shape (e.g. "CONNECT HEALTH CONNECT", "SHARE LINK").
struct FITWARSecondaryButton: View {
    let title: String
    var isDisabled: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(FWTypography.buttonLabel)
                .tracking(0.6)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 17)
                .foregroundStyle(FWColor.textPrimary)
                .background(FWColor.surface2)
                .overlay(
                    RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous)
                        .strokeBorder(FWColor.line)
                )
                .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous))
        }
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.4 : 1)
        .buttonStyle(FWPressableStyle())
    }
}

/// Ghost/text button: transparent, dim — "I already have an account", "Skip for now".
struct FITWARTextButton: View {
    let title: String
    var color: Color = FWColor.textDim
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(FWTypography.bodyMedium)
                .foregroundStyle(color)
                .padding(.vertical, FWSpacing.xs)
        }
        .buttonStyle(FWPressableStyle(scaleAmount: 0.98))
    }
}

/// Shared press-feedback (`style-active{transform:scale(.985)}` in the prototype).
struct FWPressableStyle: ButtonStyle {
    var scaleAmount: CGFloat = 0.985

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scaleAmount : 1)
            .animation(FWAnimation.press, value: configuration.isPressed)
    }
}
