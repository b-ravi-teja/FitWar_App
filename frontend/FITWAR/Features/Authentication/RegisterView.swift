import SwiftUI

/// Only what the backend actually needs at account creation (email, password,
/// display name) — no unnecessary fields (this phase's §12: "Do not ask for
/// unnecessary information at account creation"). Fitness level/avatar belong to
/// onboarding's profile step, not registration.
struct RegisterView: View {
    @State private var viewModel: RegisterViewModel
    var onBack: () -> Void

    init(sessionManager: SessionManager, onBack: @escaping () -> Void) {
        _viewModel = State(initialValue: RegisterViewModel(sessionManager: sessionManager))
        self.onBack = onBack
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                HStack {
                    Button(action: onBack) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(FWColor.textPrimary)
                            .frame(width: 34, height: 34)
                            .overlay(Circle().strokeBorder(FWColor.line))
                    }
                    .accessibilityLabel("Back")
                    Spacer()
                }
                .padding(.top, FWSpacing.xl)

                Text("Create your account")
                    .font(FWTypography.displayLarge)
                    .foregroundStyle(FWColor.textPrimary)

                VStack(spacing: FWSpacing.xl) {
                    FWTextField(label: "Display name", text: $viewModel.displayName, placeholder: "Ravi", textContentType: .name)
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
                        placeholder: "At least 8 characters",
                        isSecure: true,
                        textContentType: .newPassword
                    )
                }

                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .accessibilityLabel("Error: \(errorMessage)")
                }

                Spacer(minLength: FWSpacing.xxl)

                FITWARPrimaryButton(
                    title: "CREATE ACCOUNT",
                    isLoading: viewModel.isLoading,
                    isDisabled: !viewModel.canSubmit,
                    action: { Task { await viewModel.submit() } }
                )
            }
            .padding(.horizontal, FWSpacing.screenHorizontal + 4)
            .padding(.bottom, FWSpacing.xxl)
        }
        .background(FWColor.background)
        .scrollDismissesKeyboard(.interactively)
    }
}
