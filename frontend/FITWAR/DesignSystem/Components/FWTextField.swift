import SwiftUI

/// Underline text field — the design's only text-input pattern (onboarding's username
/// field: `border-bottom:1px solid var(--line2);padding-bottom:8px`), reused here for
/// every form FITWAR needs (Login/Register/Password Reset) since none of those screens
/// exist in the prototype but this input style does.
struct FWTextField: View {
    let label: String
    @Binding var text: String
    var placeholder: String = ""
    var isSecure: Bool = false
    var keyboardType: UIKeyboardType = .default
    var textContentType: UITextContentType? = nil
    var errorMessage: String? = nil

    @FocusState private var isFocused: Bool
    @State private var isSecureTextVisible = false

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xs) {
            Text(label)
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.metaLabel)
                .textCase(.uppercase)
                .foregroundStyle(FWColor.textDim2)

            HStack {
                Group {
                    if isSecure, !isSecureTextVisible {
                        SecureField(placeholder, text: $text)
                    } else {
                        TextField(placeholder, text: $text)
                    }
                }
                .font(FWTypography.titleSmall)
                .foregroundStyle(FWColor.textPrimary)
                .keyboardType(keyboardType)
                .textContentType(textContentType)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($isFocused)
                .accessibilityLabel(label)

                if isSecure {
                    Button {
                        isSecureTextVisible.toggle()
                    } label: {
                        Image(systemName: isSecureTextVisible ? "eye.slash" : "eye")
                            .foregroundStyle(FWColor.textDim2)
                    }
                    .accessibilityLabel(isSecureTextVisible ? "Hide password" : "Show password")
                }
            }
            .padding(.bottom, FWSpacing.sm)
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(errorMessage != nil ? FWColor.red : (isFocused ? FWColor.accent : FWColor.line2))
                    .frame(height: 1)
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(FWTypography.caption)
                    .foregroundStyle(FWColor.red)
                    .accessibilityLabel("Error: \(errorMessage)")
            }
        }
        // Deliberately NOT `.accessibilityElement(children: .combine)`: this field
        // can contain two independently-interactive children (the text input and,
        // for secure fields, the show/hide toggle) — combining them into one opaque
        // element breaks VoiceOver's ability to reach either individually, and broke
        // XCUITest's ability to focus the password field the same way (found during
        // Phase 2 validation — the label is set directly on the input above instead).
    }
}
