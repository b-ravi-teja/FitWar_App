import SwiftUI

/// Minimum V1 flow (this phase's §13): email → request → enter the emailed token +
/// new password → confirm. There's no deep-link handling of the reset email yet, so
/// the token is entered manually — a deliberate, documented V1 simplification, not
/// an oversight (deep-linking is a natural fast-follow once transactional email is
/// wired up in a real deployment; Architecture §6/ADR 0007 already designed for it).
struct ForgotPasswordView: View {
    @Environment(\.authService) private var authService
    @Environment(\.dismiss) private var dismiss
    @State private var viewModel: ForgotPasswordViewModel?

    var body: some View {
        NavigationStack {
            content
                .padding(.horizontal, FWSpacing.screenHorizontal + 4)
                .padding(.top, FWSpacing.xxl)
                .background(FWColor.background)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Close") { dismiss() }
                    }
                }
        }
        .onAppear {
            if viewModel == nil {
                viewModel = ForgotPasswordViewModel(authService: authService)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let viewModel {
            switch viewModel.step {
            case .enterEmail:
                emailStep(viewModel)
            case .enterNewPassword:
                newPasswordStep(viewModel)
            case .done:
                doneStep
            }
        } else {
            LoadingView()
        }
    }

    private func emailStep(_ viewModel: ForgotPasswordViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(
                eyebrow: "RESET PASSWORD",
                title: "Forgot your password?",
                subtitle: "Enter your email and we'll send you a reset code."
            )

            FWTextField(
                label: "Email",
                text: Binding(get: { viewModel.email }, set: { viewModel.email = $0 }),
                placeholder: "you@example.com",
                keyboardType: .emailAddress,
                textContentType: .username
            )

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage).font(FWTypography.bodySmall).foregroundStyle(FWColor.red)
            }

            Spacer()

            FITWARPrimaryButton(
                title: "SEND RESET CODE",
                isLoading: viewModel.isLoading,
                isDisabled: !viewModel.canRequestReset,
                action: { Task { await viewModel.requestReset() } }
            )
            .padding(.bottom, FWSpacing.xxl)
        }
    }

    private func newPasswordStep(_ viewModel: ForgotPasswordViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(
                eyebrow: "CHECK YOUR EMAIL",
                title: "Enter your reset code",
                subtitle: "If an account exists for that email, a code is on its way."
            )

            VStack(spacing: FWSpacing.xl) {
                FWTextField(label: "Reset code", text: Binding(get: { viewModel.resetToken }, set: { viewModel.resetToken = $0 }), placeholder: "Paste the code from your email")
                FWTextField(
                    label: "New password",
                    text: Binding(get: { viewModel.newPassword }, set: { viewModel.newPassword = $0 }),
                    placeholder: "At least 8 characters",
                    isSecure: true,
                    textContentType: .newPassword
                )
            }

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage).font(FWTypography.bodySmall).foregroundStyle(FWColor.red)
            }

            Spacer()

            FITWARPrimaryButton(
                title: "RESET PASSWORD",
                isLoading: viewModel.isLoading,
                isDisabled: !viewModel.canConfirmReset,
                action: { Task { await viewModel.confirmReset() } }
            )
            .padding(.bottom, FWSpacing.xxl)
        }
    }

    private var doneStep: some View {
        VStack(spacing: FWSpacing.xl) {
            Spacer()
            Circle()
                .fill(FWColor.accent)
                .frame(width: 64, height: 64)
                .overlay(Image(systemName: "checkmark").font(.system(size: 24, weight: .bold)).foregroundStyle(FWColor.onAccent))
            Text("Password reset")
                .font(FWTypography.titleLarge)
                .foregroundStyle(FWColor.textPrimary)
            Text("Log in with your new password.")
                .font(FWTypography.body)
                .foregroundStyle(FWColor.textDim)
            Spacer()
            FITWARPrimaryButton(title: "DONE") { dismiss() }
                .padding(.bottom, FWSpacing.xxl)
        }
    }
}
