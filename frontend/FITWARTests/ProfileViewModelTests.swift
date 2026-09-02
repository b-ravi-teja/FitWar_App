import Foundation
import Testing
@testable import FITWAR

@MainActor
struct ProfileViewModelTests {
    private func makeSUT(fetchResult: Result<User, Error>) -> ProfileViewModel {
        let userService = MockUserService()
        userService.fetchResult = fetchResult
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sessionManager = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return ProfileViewModel(userService: userService, sessionManager: sessionManager)
    }

    @Test func loadSuccessPopulatesUser() async {
        let user = User(id: UUID(), email: "ravi@example.com", displayName: "Ravi", avatarMediaId: nil, xpTotal: 0, notificationPreferences: nil)
        let sut = makeSUT(fetchResult: .success(user))

        await sut.load()

        #expect(sut.loadState == .loaded(user))
    }

    @Test func loadNetworkFailureMapsToNetworkErrorState() async {
        let sut = makeSUT(fetchResult: .failure(APIError.noConnection))
        await sut.load()
        #expect(sut.loadState == .networkError)
    }

    @Test func loadServerFailureMapsToServerErrorState() async {
        let sut = makeSUT(fetchResult: .failure(APIError.server(status: 500, code: "INTERNAL_ERROR", detail: "oops")))
        await sut.load()
        #expect(sut.loadState == .serverError)
    }

    @Test func provisionalLevelFormulaIsDeterministic() {
        #expect(ProfileViewModel.provisionalLevel(forXP: 0) == 1)
        #expect(ProfileViewModel.provisionalLevel(forXP: 1000) == 2)
        #expect(ProfileViewModel.provisionalLevel(forXP: 2500) == 3)
    }
}
