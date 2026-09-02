import SwiftUI

/// Shared full-screen error template — icon swatch + headline + body + optional hint
/// box + primary/secondary actions. Source: the prototype's permission-error screen
/// (`errPerm`), reused for every generic error state per the design spec (§20.10):
/// "all reusable from the existing permission-error style."
struct GenericStateView: View {
    let symbol: String
    let title: String
    let message: String
    var hint: String? = nil
    var primaryActionTitle: String? = nil
    var primaryAction: (() -> Void)? = nil
    var secondaryActionTitle: String? = nil
    var secondaryAction: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            RoundedRectangle(cornerRadius: FWRadius.small + 6, style: .continuous)
                .strokeBorder(FWColor.line2)
                .background(FWColor.surface)
                .frame(width: 46, height: 46)
                .overlay(
                    Image(systemName: symbol)
                        .font(.system(size: 18, weight: .medium))
                        .foregroundStyle(FWColor.textDim)
                )
                .clipShape(RoundedRectangle(cornerRadius: FWRadius.small + 6, style: .continuous))

            Text(title)
                .font(FWTypography.displayMedium)
                .foregroundStyle(FWColor.textPrimary)

            Text(message)
                .font(FWTypography.body)
                .foregroundStyle(FWColor.textDim)
                .fixedSize(horizontal: false, vertical: true)

            if let hint {
                Text(hint)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textDim)
                    .padding(FWSpacing.lg)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(RoundedRectangle(cornerRadius: FWRadius.medium, style: .continuous).strokeBorder(FWColor.line))
            }

            Spacer(minLength: FWSpacing.lg)

            VStack(spacing: FWSpacing.sm + 2) {
                if let primaryActionTitle, let primaryAction {
                    FITWARPrimaryButton(title: primaryActionTitle, action: primaryAction)
                }
                if let secondaryActionTitle, let secondaryAction {
                    FITWARTextButton(title: secondaryActionTitle, action: secondaryAction)
                }
            }
        }
        .padding(.horizontal, FWSpacing.screenHorizontal + 4)
        .padding(.top, 100)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
        .accessibilityElement(children: .contain)
    }
}

struct NetworkErrorView: View {
    var onRetry: () -> Void

    var body: some View {
        GenericStateView(
            symbol: "wifi.slash",
            title: "No connection",
            message: "FITWAR couldn't reach the server. Check your connection and try again.",
            primaryActionTitle: "RETRY",
            primaryAction: onRetry
        )
    }
}

struct ServerErrorView: View {
    var onRetry: () -> Void

    var body: some View {
        GenericStateView(
            symbol: "exclamationmark.triangle",
            title: "Something went wrong",
            message: "The server ran into a problem on our end. This isn't something you did.",
            primaryActionTitle: "RETRY",
            primaryAction: onRetry
        )
    }
}

struct UnauthorizedView: View {
    var onLogIn: () -> Void

    var body: some View {
        GenericStateView(
            symbol: "lock",
            title: "Session expired",
            message: "You've been logged out. Log back in to keep going.",
            primaryActionTitle: "LOG IN AGAIN",
            primaryAction: onLogIn
        )
    }
}

struct PermissionErrorView: View {
    enum Kind {
        case health, camera

        var title: String { self == .health ? "Health access denied" : "Camera access denied" }
        var message: String {
            self == .health
                ? "Without health data we can't auto-verify your steps."
                : "FITWAR needs the camera to record your proof clip."
        }
        var hint: String {
            self == .health
                ? "You can still play — teammates verify your manual entries instead of Apple Health."
                : "You can upload an existing clip from your library instead."
        }
    }

    let kind: Kind
    var onOpenSettings: () -> Void
    var onAlternative: (() -> Void)? = nil

    var body: some View {
        GenericStateView(
            symbol: kind == .health ? "heart.slash" : "camera.slash",
            title: kind.title,
            message: kind.message,
            hint: kind.hint,
            primaryActionTitle: "OPEN SETTINGS",
            primaryAction: onOpenSettings,
            secondaryActionTitle: onAlternative != nil ? "Continue without it" : nil,
            secondaryAction: onAlternative
        )
    }
}

/// Empty state: dashed icon swatch + headline + body + CTA (distinct treatment from
/// the error template — matches the design's Challenges-empty pattern exactly).
struct EmptyStateView: View {
    let title: String
    let message: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: FWSpacing.md) {
            RoundedRectangle(cornerRadius: FWRadius.small + 10, style: .continuous)
                .strokeBorder(FWColor.line2, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                .frame(width: 56, height: 56)

            Text(title)
                .font(FWTypography.titleSmall)
                .foregroundStyle(FWColor.textPrimary)

            Text(message)
                .font(FWTypography.bodySmall)
                .foregroundStyle(FWColor.textDim)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 230)

            if let actionTitle, let action {
                Button(action: action) {
                    Text(actionTitle)
                        .font(FWTypography.buttonLabel)
                        .tracking(0.6)
                        .padding(.horizontal, FWSpacing.xl)
                        .padding(.vertical, FWSpacing.md + 2)
                        .foregroundStyle(FWColor.onAccent)
                        .background(FWColor.accent)
                        .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium - 2, style: .continuous))
                }
                .buttonStyle(FWPressableStyle())
                .padding(.top, FWSpacing.xxs)
            }
        }
        .padding(.vertical, 60)
        .padding(.horizontal, FWSpacing.xl)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// Loading state: centered spinner. Deliberately lighter-weight than the error
/// template (a loading moment shouldn't compete visually with an actual failure).
struct LoadingView: View {
    var label: String? = nil

    var body: some View {
        VStack(spacing: FWSpacing.md) {
            ProgressView()
                .progressViewStyle(.circular)
                .tint(FWColor.accent)
            if let label {
                Text(label)
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(FWColor.background)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label ?? "Loading")
        .accessibilityAddTraits(.updatesFrequently)
    }
}
