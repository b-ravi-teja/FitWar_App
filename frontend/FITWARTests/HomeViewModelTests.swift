import Foundation
import Testing

@testable import FITWAR

@MainActor
private func makeSession() -> SessionManager {
    SessionManager(
        authService: MockAuthService(),
        keychain: MockKeychainStore(),
        apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
    )
}

@MainActor
struct HomeViewModelTests {
    private func makeSUT() -> (HomeViewModel, MockChallengesService, MockGameService) {
        let challenges = MockChallengesService()
        let games = MockGameService()
        games.xpResult = .success(GameFixtures.xpSummary())
        let sut = HomeViewModel(
            challenges: challenges, games: games, sessionManager: makeSession()
        )
        return (sut, challenges, games)
    }

    @Test func todaysMissionIsAssembledFromRealServerData() async {
        /// Home surfaces existing endpoints one screen earlier — it computes no game
        /// state of its own.
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary(name: "30 DAY STEP WAR")])
        challenges.todayResult = .success(Fixture.dailyProgress(target: 10_000, unit: "steps"))
        games.myStateResult = .success(GameFixtures.gameState(rank: 2, currentStreak: 4))

        await sut.load()

        let mission = try? #require(sut.primary)
        #expect(mission?.challenge.name == "30 DAY STEP WAR")
        #expect(mission?.progress.target == 10_000)
        #expect(mission?.streak == 4)
        #expect(mission?.rank == 2)
    }

    @Test func doneTodayComesFromTheServersDayStatus() async {
        /// Not from comparing a value the client is holding — the server decides
        /// completion (Architecture §1, tenet 1).
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress(status: .completed))
        games.myStateResult = .success(GameFixtures.gameState())

        await sut.load()

        #expect(sut.primary?.isDoneToday == true)
        #expect(sut.allDoneToday)
    }

    @Test func apendingDayIsNotDone() async {
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress(status: .pending))
        games.myStateResult = .success(GameFixtures.gameState())

        await sut.load()

        #expect(sut.primary?.isDoneToday == false)
        #expect(!sut.allDoneToday)
    }

    @Test func theLeadMissionIsSomethingStillToDo() async {
        /// The CTA has to be actionable whenever anything is actionable.
        let (sut, challenges, games) = makeSUT()
        let done = UUID()
        let todo = UUID()
        challenges.listMineResult = .success([
            Fixture.challengeSummary(id: done, name: "FINISHED TODAY"),
            Fixture.challengeSummary(id: todo, name: "STILL TO DO"),
        ])
        challenges.todayHandler = { id in
            Fixture.dailyProgress(status: id == done ? .completed : .pending)
        }
        games.myStateResult = .success(GameFixtures.gameState())

        await sut.load()

        #expect(sut.primary?.challenge.name == "STILL TO DO")
        #expect(sut.others.count == 1)
    }

    @Test func noActiveChallengeIsAnHonestEmptyStateNotAnError() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .success([])

        await sut.load()

        #expect(sut.state == .loaded([]))
        #expect(sut.missions.isEmpty)
        #expect(sut.primary == nil)
    }

    @Test func challengesTheUserLeftAreNotMissions() async {
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([
            Fixture.challengeSummary(name: "LEFT", myStatus: .left),
            Fixture.challengeSummary(name: "MINE", myStatus: .active),
        ])
        challenges.todayResult = .success(Fixture.dailyProgress())
        games.myStateResult = .success(GameFixtures.gameState())

        await sut.load()

        #expect(sut.missions.map(\.challenge.name) == ["MINE"])
    }

    @Test func anEliminatedParticipantIsShownAsOutNotAsATask() async {
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress(status: .pending))
        games.myStateResult = .success(GameFixtures.gameState(status: .eliminated))

        await sut.load()

        #expect(sut.primary?.isEliminated == true)
        #expect(sut.allDoneToday, "an eliminated player has nothing left to do today")
    }

    @Test func warningsAreSurfacedFromServerState() async {
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress())
        games.myStateResult = .success(
            GameFixtures.gameState(warnings: [GameFixtures.warning()])
        )

        await sut.load()

        #expect(sut.primary?.warningCount == 1)
    }

    @Test func aMissionStillRendersWhenGameStateIsUnavailable() async {
        /// Rank and streak are supplementary; losing them must not lose the mission.
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress())
        games.myStateResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.primary != nil)
        #expect(sut.primary?.streak == 0)
        #expect(sut.primary?.rank == nil)
    }

    @Test func networkFailureIsItsOwnState() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func unauthorizedIsItsOwnState() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .failure(
            APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "nope")
        )

        await sut.load()

        #expect(sut.state == .unauthorized)
    }

    @Test func xpIsOptionalAndItsFailureDoesNotBreakHome() async {
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary()])
        challenges.todayResult = .success(Fixture.dailyProgress())
        games.myStateResult = .success(GameFixtures.gameState())
        games.xpResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.primary != nil)
        #expect(sut.xp == nil)
    }

    @Test func everyNumberOnHomeCameFromTheServer() async {
        /// The guard against Home reintroducing fabricated statistics: each value it
        /// exposes is traceable to a specific response field.
        let (sut, challenges, games) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary(durationDays: 30)])
        challenges.todayResult = .success(Fixture.dailyProgress(dayIndex: 6, target: 12_500))
        games.myStateResult = .success(GameFixtures.gameState(rank: 3, currentStreak: 7))
        games.xpResult = .success(GameFixtures.xpSummary(level: 4, into: 220, toNext: 280))

        await sut.load()

        #expect(sut.primary?.progress.dayIndex == 6)
        #expect(sut.primary?.progress.target == 12_500)
        #expect(sut.primary?.challenge.durationDays == 30)
        #expect(sut.primary?.rank == 3)
        #expect(sut.primary?.streak == 7)
        #expect(sut.xp?.level == 4)
    }
}

// MARK: - Validation copy

struct ValidationMessagePresentationTests {
    @Test func theEmailFailureThatReachedUsersIsNowProductCopy() {
        /// Verbatim from the beta walkthrough's signup screen.
        let raw = "body.email: value is not a valid email address: The part after the "
            + "@-sign is a special-use or reserved name that cannot be used with email."

        let message = ValidationMessagePresentation.message(for: raw)

        #expect(message == "Please enter a valid email address.")
        #expect(!message.contains("body."))
        #expect(!message.lowercased().contains("@-sign"))
    }

    @Test func noMappedMessageLeaksTheFieldPathOrLibraryVocabulary() {
        let samples = [
            "body.password: String should have at least 8 characters",
            "body.display_name: String should have at most 50 characters",
            "body.content: String should have at least 1 character",
            "body.target_value: Input should be greater than 0",
            "body.duration_days: Input should be less than or equal to 365",
            "body.timezone: value is not a valid timezone",
            "body.mystery_field: Input should be a valid integer",
        ]

        for raw in samples {
            let message = ValidationMessagePresentation.message(for: raw)
            #expect(!message.contains("body."), "leaked field path: \(message)")
            #expect(!message.contains("String should"), "leaked pydantic text: \(message)")
            #expect(!message.isEmpty)
        }
    }

    @Test func anUnmappedFieldGetsAnHonestFallback() {
        let message = ValidationMessagePresentation.message(for: "body.mystery: Input should be valid")

        #expect(message == "Some details need fixing. Check the form and try again.")
    }

    @Test func onlyTheFirstFailureIsSurfaced() {
        /// Listing every failure at once is noise on a phone.
        let raw = "body.email: value is not a valid email address; body.password: too short"

        #expect(ValidationMessagePresentation.message(for: raw) == "Please enter a valid email address.")
    }

    @Test func authErrorsRouteValidationThroughTheSameMapping() {
        let error = APIError.server(
            status: 422, code: "VALIDATION_ERROR",
            detail: "body.email: value is not a valid email address"
        )

        #expect(AuthErrorPresentation.message(for: error) == "Please enter a valid email address.")
    }

    @Test func domainErrorsRouteValidationThroughTheSameMapping() {
        let error = APIError.server(
            status: 422, code: "VALIDATION_ERROR",
            detail: "body.display_name: String should have at most 50 characters"
        )

        #expect(DomainErrorPresentation.message(for: error) == "That name is too long. Try a shorter one.")
    }
}
