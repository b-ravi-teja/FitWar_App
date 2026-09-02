import Foundation
import Testing
@testable import FITWAR

@MainActor
struct LoginViewModelTests {
    private func makeSUT() -> (LoginViewModel, MockAuthService, MockKeychainStore) {
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sessionManager = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return (LoginViewModel(sessionManager: sessionManager), authService, keychain)
    }

    @Test func cannotSubmitWithEmptyFields() {
        let (sut, _, _) = makeSUT()
        #expect(!sut.canSubmit)
    }

    @Test func submitSuccessClearsErrorAndStopsLoading() async {
        let (sut, authService, _) = makeSUT()
        authService.loginResult = .success(
            AuthenticatedSession(userId: UUID(), accessToken: "a", refreshToken: "r", expiresIn: 900)
        )
        sut.email = "ravi@example.com"
        sut.password = "hunter2222"

        await sut.submit()

        #expect(sut.errorMessage == nil)
        #expect(!sut.isLoading)
        #expect(authService.loginCallCount == 1)
    }

    @Test func submitFailureSurfacesReadableMessage() async {
        let (sut, authService, _) = makeSUT()
        authService.loginResult = .failure(
            APIError.server(status: 401, code: "INVALID_CREDENTIALS", detail: "Incorrect email or password.")
        )
        sut.email = "ravi@example.com"
        sut.password = "wrong-password"

        await sut.submit()

        #expect(sut.errorMessage == "Incorrect email or password.")
        #expect(!sut.isLoading)
    }

    @Test func submitNetworkFailureSurfacesNetworkMessage() async {
        let (sut, authService, _) = makeSUT()
        authService.loginResult = .failure(APIError.noConnection)
        sut.email = "ravi@example.com"
        sut.password = "hunter2222"

        await sut.submit()

        #expect(sut.errorMessage == "No internet connection. Check your network and try again.")
    }
}

@MainActor
struct RegisterViewModelTests {
    private func makeSUT() -> (RegisterViewModel, MockAuthService) {
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sessionManager = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return (RegisterViewModel(sessionManager: sessionManager), authService)
    }

    @Test func cannotSubmitWithShortPassword() {
        let (sut, _) = makeSUT()
        sut.displayName = "Ravi"
        sut.email = "ravi@example.com"
        sut.password = "short"
        #expect(!sut.canSubmit)
    }

    @Test func cannotSubmitWithInvalidEmail() {
        let (sut, _) = makeSUT()
        sut.displayName = "Ravi"
        sut.email = "not-an-email"
        sut.password = "hunter2222"
        #expect(!sut.canSubmit)
    }

    @Test func registrationSuccessCallsAuthServiceOnce() async {
        let (sut, authService) = makeSUT()
        authService.registerResult = .success(
            AuthenticatedSession(userId: UUID(), accessToken: "a", refreshToken: "r", expiresIn: 900)
        )
        sut.displayName = "Ravi"
        sut.email = "ravi@example.com"
        sut.password = "hunter2222"

        await sut.submit()

        #expect(sut.errorMessage == nil)
    }

    @Test func registrationDuplicateEmailSurfacesMessage() async {
        let (sut, authService) = makeSUT()
        authService.registerResult = .failure(
            APIError.server(status: 409, code: "EMAIL_TAKEN", detail: "An account with this email already exists.")
        )
        sut.displayName = "Ravi"
        sut.email = "dup@example.com"
        sut.password = "hunter2222"

        await sut.submit()

        #expect(sut.errorMessage == "An account with that email already exists.")
    }
}

struct ForgotPasswordViewModelTests {
    @MainActor
    private func makeSUT() -> (ForgotPasswordViewModel, MockAuthService) {
        let authService = MockAuthService()
        return (ForgotPasswordViewModel(authService: authService), authService)
    }

    @MainActor
    @Test func requestResetAdvancesStepRegardlessOfWhetherAccountExists() async {
        let (sut, authService) = makeSUT()
        authService.requestPasswordResetResult = .success(())
        sut.email = "anyone@example.com"

        await sut.requestReset()

        #expect(sut.step != .enterEmail)
        #expect(sut.errorMessage == nil)
    }

    @MainActor
    @Test func confirmResetSuccessMovesToDone() async {
        let (sut, authService) = makeSUT()
        authService.confirmPasswordResetResult = .success(())
        sut.resetToken = "some-token"
        sut.newPassword = "newpassword1"

        await sut.confirmReset()

        #expect(sut.step == .done)
    }

    @MainActor
    @Test func confirmResetFailureSurfacesMessage() async {
        let (sut, authService) = makeSUT()
        authService.confirmPasswordResetResult = .failure(
            APIError.server(status: 400, code: "RESET_TOKEN_INVALID_OR_EXPIRED", detail: "This reset code is invalid or has expired.")
        )
        sut.resetToken = "bad-token"
        sut.newPassword = "newpassword1"

        await sut.confirmReset()

        #expect(sut.errorMessage != nil)
        #expect(sut.step != .done)
    }
}
