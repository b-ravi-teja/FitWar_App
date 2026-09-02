import Foundation
import Testing

@testable import FITWAR

@MainActor
struct LeaderboardViewModelTests {
    private func makeSUT() -> (LeaderboardViewModel, MockGameService) {
        let games = MockGameService()
        return (LeaderboardViewModel(challengeId: UUID(), games: games), games)
    }

    @Test func loadsServerRankedStandings() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .success(
            GameFixtures.leaderboard(entries: [
                GameFixtures.entry(rank: 1, name: "Alpha", score: 900),
                GameFixtures.entry(rank: 2, name: "Bravo", score: 100),
            ])
        )

        await sut.load()

        let board = try? #require(sut.state.value)
        #expect(board?.entries.map(\.rank) == [1, 2])
    }

    @Test func preservesServerOrderWithoutResorting() async {
        /// Rank is the server's answer. If the client re-sorted, a tie broken by the
        /// frozen rule (not by score) would be silently reordered here.
        let (sut, games) = makeSUT()
        let tiedLower = GameFixtures.entry(rank: 1, name: "Early", score: 500)
        let tiedHigher = GameFixtures.entry(rank: 2, name: "Late", score: 500)
        games.leaderboardResult = .success(
            GameFixtures.leaderboard(entries: [tiedLower, tiedHigher])
        )

        await sut.load()

        #expect(sut.state.value?.entries.map(\.displayName) == ["Early", "Late"])
    }

    @Test func networkFailureIsItsOwnState() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func unauthorizedIsItsOwnState() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .failure(
            APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "nope")
        )

        await sut.load()

        #expect(sut.state == .unauthorized)
    }

    @Test func serverErrorSurfacesAMessage() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .failure(
            APIError.server(status: 500, code: "INTERNAL_ERROR", detail: "boom")
        )

        await sut.load()

        guard case .serverError = sut.state else {
            Issue.record("expected serverError, got \(sut.state)")
            return
        }
    }

    @Test func anEmptyBoardIsLoadedNotAnError() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .success(
            Leaderboard(challengeId: UUID(), gameMode: "survival", isFinal: false, entries: [])
        )

        await sut.load()

        #expect(sut.state.value?.entries.isEmpty == true)
    }

    @Test func finalStandingsAreFlagged() async {
        let (sut, games) = makeSUT()
        games.leaderboardResult = .success(GameFixtures.leaderboard(isFinal: true))

        await sut.load()

        #expect(sut.state.value?.isFinal == true)
    }
}
