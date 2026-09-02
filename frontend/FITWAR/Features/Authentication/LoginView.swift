import SwiftUI

/// Not present in `FITWAR.dc.html` — the prototype only references it via
/// onboarding's "I already have an account" link (design spec §20.8, added by the
/// approved product decisions). Built from the same visual language as every other
/// screen: eyebrow + headline pattern, underline inputs, full-width pill CTA.
struct LoginView: View {
    @Environment(SessionManager.self) private var sessionManager
    @State private var viewModel: LoginViewModel
    @State private var showForgotPassword = false
    var onGoToRegister: () -> Void

    init(sessionManager: SessionManager, onGoToRegister: @escaping () -> Void) {
        _viewModel = State(initialValue: LoginViewModel(sessionManager: sessionManager))
        self.onGoToRegister = onGoToRegister
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                VStack(alignment: .leading, spacing: FWSpacing.sm) {
                    Text("FITWAR")
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.eyebrow)
                        .foregroundStyle(FWColor.accent)
                    Text("Welcome back.")
                        .font(FWTypography.heroHeadline)
                        .foregroundStyle(FWColor.textPrimary)
                }
                .padding(.top, 80)

                VStack(spacing: FWSpacing.xl) {
                    FWTextField(
                        label: "Email",
                        text: $viewModel.email,
                        placeholder: "you@example.com",
                        keyboardType: .emailAddress,
                        textContentType: .username
                    )
                    FWTextField(
                        label: "Password",
                        text: $viewModel.password,
                        placeholder: "••••••••",
                        isSecure: true,
                        textContentType: .password
                    )
                }

                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .accessibilityLabel("Error: \(errorMessage)")
                }

                FITWARTextButton(title: "Forgot password?") {
                    showForgotPassword = true
                }

                Spacer(minLength: FWSpacing.xxl)

                VStack(spacing: FWSpacing.md) {
                    FITWARPrimaryButton(
                        title: "LOG IN",
                        isLoading: viewModel.isLoading,
                        isDisabled: !viewModel.canSubmit,
                        action: { Task { await viewModel.submit() } }
                    )
                    FITWARTextButton(title: "Don't have an account? Sign up", action: onGoToRegister)
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal + 4)
            .padding(.bottom, FWSpacing.xxl)
        }
        .background(FWColor.background)
        .scrollDismissesKeyboard(.interactively)
        .sheet(isPresented: $showForgotPassword) {
            ForgotPasswordView()
        }
    }
}
