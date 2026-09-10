import Foundation
import Testing
@testable import FITWAR

@MainActor
struct ProfileViewModelTests {
    private func makeSUT(
        fetchResult: Result<User, Error>, games: MockGameService = MockGameService()
    ) -> ProfileViewModel {
        let userService = MockUserService()
        userService.fetchResult = fetchResult
        let authService = MockAuthService()
        let keychain = MockKeychainStore()
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let sessionManager = SessionManager(authService: authService, keychain: keychain, apiClient: apiClient)
        return ProfileViewModel(
            userService: userService,
            gameService: games,
            sessionManager: sessionManager
        )
    }

    @Test func loadSuccessPopulatesUser() async {
        let user = UserFixtures.user(xpTotal: 0)
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

    @Test func levelComesFromTheServerNotAClientFormula() async {
        /// Phase 5 moved leveling to the server. The provisional client-side formula
        /// this test used to assert is gone on purpose — two authorities disagreeing
        /// about a user's level is exactly the bug the change prevents.
        let games = MockGameService()
        games.xpResult = .success(GameFixtures.xp(total: 2500, level: 6))
        let sut = makeSUT(fetchResult: .success(UserFixtures.user(xpTotal: 2500)), games: games)

        await sut.load()

        #expect(sut.xpSummary?.level == 6)
    }

    @Test func aFailedXPLoadDoesNotBreakTheProfile() async {
        /// The badge degrades; the screen still renders.
        let games = MockGameService()
        games.xpResult = .failure(APIError.noConnection)
        let sut = makeSUT(fetchResult: .success(UserFixtures.user(xpTotal: 2500)), games: games)

        await sut.load()

        #expect(sut.xpSummary == nil)
        if case .loaded = sut.loadState {} else {
            Issue.record("profile should still load, got \(sut.loadState)")
        }
    }
}
