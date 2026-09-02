import Foundation

enum ForgotPasswordStep: Equatable {
    case enterEmail
    case enterNewPassword(token: String)
    case done
}

/// The backend's `/auth/password-reset/request` always returns 202 regardless of
/// whether the email exists (Architecture §20.8/ADR 0007) — this view model never
/// branches on "found" vs "not found" for that reason (this phase's §13: "Do not
/// expose whether an email exists").
@MainActor
@Observable
final class ForgotPasswordViewModel {
    var email = ""
    var resetToken = ""
    var newPassword = ""
    private(set) var step: ForgotPasswordStep = .enterEmail
    private(set) var isLoading = false
    private(set) var errorMessage: String?

    private let authService: AuthServiceProtocol

    init(authService: AuthServiceProtocol) {
        self.authService = authService
    }

    var canRequestReset: Bool { email.contains("@") && !isLoading }
    var canConfirmReset: Bool { !resetToken.isEmpty && newPassword.count >= 8 && !isLoading }

    func requestReset() async {
        guard canRequestReset else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await authService.requestPasswordReset(email: email.trimmingCharacters(in: .whitespaces))
            // Always advances, regardless of whether the account exists — the backend
            // response carries no signal either way, by design.
            step = .enterNewPassword(token: "")
        } catch {
            errorMessage = AuthErrorPresentation.message(for: error)
        }
    }

    func confirmReset() async {
        guard canConfirmReset else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await authService.confirmPasswordReset(token: resetToken, newPassword: newPassword)
            step = .done
        } catch {
            errorMessage = AuthErrorPresentation.message(for: error)
        }
    }
}
