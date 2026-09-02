import Foundation

@MainActor
@Observable
final class RegisterViewModel {
    var email = ""
    var password = ""
    var displayName = ""
    private(set) var isLoading = false
    private(set) var errorMessage: String?

    private let sessionManager: SessionManager

    init(sessionManager: SessionManager) {
        self.sessionManager = sessionManager
    }

    /// Matches the backend's Pydantic validation (`schemas/auth.py`) so the client
    /// fails fast with the same rule rather than round-tripping an obvious 422.
    var canSubmit: Bool {
        !displayName.trimmingCharacters(in: .whitespaces).isEmpty
            && email.contains("@")
            && password.count >= 8
            && !isLoading
    }

    func submit() async {
        guard canSubmit else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await sessionManager.register(
                email: email.trimmingCharacters(in: .whitespaces),
                password: password,
                displayName: displayName.trimmingCharacters(in: .whitespaces)
            )
        } catch {
            errorMessage = AuthErrorPresentation.message(for: error)
        }
    }
}
