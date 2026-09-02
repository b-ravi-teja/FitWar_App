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
struct ChallengesListViewModelTests {
    private func makeSUT() -> (
        ChallengesListViewModel, MockChallengesService, MockGroupsService
    ) {
        let challenges = MockChallengesService()
        let groups = MockGroupsService()
        let sut = ChallengesListViewModel(
            challengesService: challenges,
            groupsService: groups,
            sessionManager: makeSession()
        )
        return (sut, challenges, groups)
    }

    @Test func loadsActiveChallengesByDefault() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .success([Fixture.challengeSummary(name: "STEP WAR")])

        await sut.load()

        #expect(sut.challenges.map(\.name) == ["STEP WAR"])
        #expect(challenges.requestedStatuses == [.active])
    }

    @Test func completedTabRequestsCompletedStatus() async {
        let (sut, challenges, _) = makeSUT()
        sut.selectedTab = .completed

        await sut.load()

        #expect(challenges.requestedStatuses.last == .completed)
    }

    @Test func onlyTwoTabsShip() {
        // The prototype's DISCOVER tab is dropped in V1 (ADR 0001).
        #expect(ChallengesListViewModel.Tab.allCases.map(\.rawValue) == ["ACTIVE", "COMPLETED"])
    }

    @Test func creationIsBlockedWithoutAGroup() async {
        let (sut, challenges, groups) = makeSUT()
        challenges.listMineResult = .success([])
        groups.listResult = .success([])

        await sut.load()

        #expect(sut.canCreate == false)
    }

    @Test func creationIsAvailableOnceInAGroup() async {
        let (sut, challenges, groups) = makeSUT()
        challenges.listMineResult = .success([])
        groups.listResult = .success([Fixture.groupSummary()])

        await sut.load()

        #expect(sut.canCreate)
    }

    @Test func networkFailureSurfacesTheNetworkErrorState() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .failure(APIError.timeout)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func unauthorizedSurfacesTheUnauthorizedState() async {
        let (sut, challenges, _) = makeSUT()
        challenges.listMineResult = .failure(
            APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "expired")
        )

        await sut.load()

        #expect(sut.state == .unauthorized)
    }
}

@MainActor
struct ChallengeDetailViewModelTests {
    private func makeSUT(
        currentUserId: UUID? = nil
    ) -> (ChallengeDetailViewModel, MockChallengesService) {
        let challenges = MockChallengesService()
        let sut = ChallengeDetailViewModel(
            challengeId: UUID(),
            challengesService: challenges,
            sessionManager: makeSession(),
            currentUserId: currentUserId
        )
        return (sut, challenges)
    }

    @Test func loadsDetailAndTodaysProgressForAnActiveParticipant() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail())
        challenges.todayResult = .success(Fixture.dailyProgress())

        await sut.load()

        #expect(sut.state.value?.challenge.name == "30 DAY STEP WAR")
        #expect(sut.state.value?.todayProgress?.status == .pending)
    }

    @Test func skipsTodaysProgressWhenNotAParticipant() async {
        // Asking would be a guaranteed 403 — an expected condition, not an error.
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail(myStatus: nil))
        challenges.todayResult = .failure(
            APIError.server(status: 403, code: "NOT_A_PARTICIPANT", detail: "no")
        )

        await sut.load()

        #expect(sut.state.value?.todayProgress == nil)
        #expect(sut.state.value?.challenge.myStatus == nil)
    }

    @Test func skipsTodaysProgressForAFinishedChallenge() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(
            Fixture.challengeDetail(status: .completed, myStatus: .completed)
        )

        await sut.load()

        #expect(sut.state.value?.todayProgress == nil)
    }

    @Test func joinRefetchesRatherThanPatchingLocalState() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail(myStatus: nil))
        challenges.joinResult = .success(Fixture.challengeDetail(myStatus: .active))

        await sut.load()
        let fetchesBeforeJoin = challenges.fetchCallCount
        challenges.fetchResult = .success(
            Fixture.challengeDetail(myStatus: .active, participants: [Fixture.participant()])
        )
        await sut.join()

        #expect(challenges.joinCallCount == 1)
        // The server owns participant count and my status — the ViewModel re-reads them.
        #expect(challenges.fetchCallCount > fetchesBeforeJoin)
        #expect(sut.state.value?.challenge.myStatus == .active)
    }

    @Test func joinFailureShowsTheMappedMessageAndLeavesStateIntact() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail(myStatus: nil))
        await sut.load()

        challenges.joinResult = .failure(
            APIError.server(status: 409, code: "PARTICIPANT_LIMIT_REACHED", detail: "full")
        )
        await sut.join()

        #expect(sut.actionError == "This challenge is full.")
        #expect(sut.state.value?.challenge.myStatus == nil)
    }

    @Test func cannotRejoinSurfacesItsOwnMessage() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail(myStatus: .left))
        await sut.load()

        challenges.joinResult = .failure(
            APIError.server(status: 409, code: "CANNOT_REJOIN", detail: "raw")
        )
        await sut.join()

        #expect(sut.actionError == "You can't re-enter a challenge you already left or finished.")
    }

    @Test func leaveRefetchesAfterSucceeding() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail())
        await sut.load()
        let before = challenges.fetchCallCount

        challenges.fetchResult = .success(Fixture.challengeDetail(myStatus: .left))
        await sut.leave()

        #expect(challenges.leaveCallCount == 1)
        #expect(challenges.fetchCallCount > before)
        #expect(sut.state.value?.challenge.myStatus == .left)
    }

    @Test func leaveFailureOnAnEndedChallengeShowsItsMessage() async {
        let (sut, challenges) = makeSUT()
        challenges.fetchResult = .success(Fixture.challengeDetail())
        await sut.load()

        challenges.leaveError = APIError.server(
            status: 409, code: "CHALLENGE_ALREADY_ENDED", detail: "raw"
        )
        await sut.leave()

        #expect(sut.actionError == "This challenge has already ended.")
    }
}

@MainActor
struct CreateChallengeViewModelTests {
    private func makeSUT() -> (
        CreateChallengeViewModel, MockChallengesService, MockGroupsService, GroupSummary
    ) {
        let group = Fixture.groupSummary()
        let challenges = MockChallengesService()
        let groups = MockGroupsService()
        let sut = CreateChallengeViewModel(
            group: group,
            challengesService: challenges,
            groupsService: groups,
            sessionManager: makeSession()
        )
        return (sut, challenges, groups, group)
    }

    @Test func walksForwardAndBackThroughAllFiveSteps() {
        let (sut, _, _, _) = makeSUT()

        #expect(sut.step == .activity)
        #expect(sut.isFirstStep)
        sut.advance()
        #expect(sut.step == .mode)
        sut.advance()
        sut.advance()
        sut.advance()
        #expect(sut.step == .review)
        // The last step doesn't run off the end.
        sut.advance()
        #expect(sut.step == .review)
        sut.goBack()
        #expect(sut.step == .invite)
    }

    @Test func ctaLabelMatchesTheDesignsPerStepCopy() {
        #expect(CreateChallengeViewModel.Step.activity.ctaTitle == "CONTINUE")
        #expect(CreateChallengeViewModel.Step.invite.ctaTitle == "CONTINUE")
        #expect(CreateChallengeViewModel.Step.review.ctaTitle == "START CHALLENGE")
    }

    @Test func pickingAnActivityResetsTheTargetToThatActivitysDefault() {
        let (sut, _, _, _) = makeSUT()
        sut.select(activity: .steps)
        #expect(sut.targetValue == 10_000)

        sut.select(activity: .pushups)

        // Otherwise a push-up challenge would inherit a 10,000-rep daily target.
        #expect(sut.targetValue == 50)
        #expect(sut.activity.unit == "reps")
    }

    @Test func nameFallsBackToASuggestionWhenLeftBlank() {
        let (sut, _, _, _) = makeSUT()
        sut.select(activity: .steps)
        sut.name = "   "

        #expect(sut.resolvedName == "30 DAY STEPS WAR")
    }

    @Test func customNameIsKept() {
        let (sut, _, _, _) = makeSUT()
        sut.name = "OFFICE STEP WAR"

        #expect(sut.resolvedName == "OFFICE STEP WAR")
    }

    @Test func failureRuleCopyIsModeSpecific() {
        let (sut, _, _, _) = makeSUT()
        sut.mode = .survival
        #expect(sut.failureRuleLabel == "2 MISSES → OUT")

        sut.mode = .points
        // POINTS has no elimination (ADR 0004).
        #expect(sut.failureRuleLabel == "NO ELIMINATION")
    }

    @Test func submitSendsTheConfiguredChallengeToItsGroup() async {
        let (sut, challenges, _, group) = makeSUT()
        sut.select(activity: .pushups)
        sut.mode = .points
        sut.verification = .manualProof
        sut.durationDays = 14
        sut.targetValue = 40
        sut.name = "PUSH WAR"
        challenges.createResult = .success(Fixture.challengeDetail())

        let created = await sut.submit()

        #expect(created != nil)
        #expect(challenges.createdGroupIds == [group.id])
        let request = try? #require(challenges.createdRequests.first)
        #expect(request?.name == "PUSH WAR")
        #expect(request?.activityType == .pushups)
        #expect(request?.gameMode == .points)
        #expect(request?.verificationMethod == .manualProof)
        #expect(request?.durationDays == 14)
        #expect(request?.targetValue == "40")
        #expect(request?.unit == "reps")
    }

    @Test func submitFailureShowsTheMappedMessage() async {
        let (sut, challenges, _, _) = makeSUT()
        challenges.createResult = .failure(
            APIError.server(status: 403, code: "NOT_A_MEMBER", detail: "raw")
        )

        let created = await sut.submit()

        #expect(created == nil)
        #expect(sut.errorMessage == "You're not a member of this squad.")
    }

    @Test func inviteStepReusesTheSquadsExistingJoinCode() async {
        let (sut, _, groups, _) = makeSUT()
        groups.fetchResult = .success(Fixture.groupDetail(joinCode: "K7-XR9"))

        await sut.loadJoinCode()

        #expect(sut.joinCode == "K7-XR9")
    }

    @Test func ruleRowsOnlyListRulesThatActuallyExist() {
        let (sut, _, _, _) = makeSUT()
        let labels = sut.ruleRows.map(\.label)

        #expect(labels == ["Duration", "Daily target", "Game mode", "Verification"])
        // "Progression" and "Rest days" from the prototype's mock list are not V1 rules.
        #expect(labels.contains("Rest days") == false)
    }
}

struct ChallengeModelTests {
    @Test func summaryMetaMatchesTheDesignsCardLine() {
        let challenge = Fixture.challengeSummary(dayIndex: 6, durationDays: 30, participantCount: 8)
        #expect(challenge.metaLine == "SURVIVAL · DAY 6/30 · 8 PLAYERS")
    }

    @Test func targetLabelIsGroupedAndUppercased() {
        #expect(Fixture.challengeSummary().targetLabel == "10,000 STEPS")
    }

    @Test func scheduleProgressTracksTheDayNotAMetric() {
        // The ring shows how far through the schedule the challenge is; there is no
        // verified daily value to show until Phase 4.
        #expect(Fixture.challengeSummary(dayIndex: 15, durationDays: 30).scheduleProgress == 0.5)
        #expect(Fixture.challengeSummary(dayIndex: 30, durationDays: 30).scheduleProgress == 1.0)
    }

    @Test func detailHeaderMatchesTheDesignsDayAndFailureRuleLine() {
        #expect(Fixture.challengeDetail().headerMeta == "DAY 6 / 30 · MISS TWICE → ELIMINATED")
    }

    @Test func pointsModeHeaderCarriesNoEliminationCopy() {
        let detail = Fixture.challengeDetail(gameMode: .points)
        #expect(detail.headerMeta.contains("ELIMINATED") == false)
    }

    @Test func joinAndLeaveAffordancesFollowServerState() {
        #expect(Fixture.challengeDetail(myStatus: nil).isJoinable)
        #expect(Fixture.challengeDetail(myStatus: .active).isJoinable == false)
        #expect(Fixture.challengeDetail(myStatus: .active).isLeavable)
        #expect(Fixture.challengeDetail(status: .completed, myStatus: .active).isLeavable == false)
        // A challenge you already left can't be re-entered (Architecture §3.3).
        #expect(Fixture.challengeDetail(myStatus: .left).isJoinable == false)
    }

    @Test func activityUnitsArePairedWithTheirActivity() {
        #expect(ActivityType.steps.unit == "steps")
        #expect(ActivityType.distance.unit == "km")
        #expect(ActivityType.pushups.unit == "reps")
        #expect(ActivityType.activeCalories.unit == "kcal")
    }

    @Test func onlyTheTwoBuiltGameModesAreSelectable() {
        #expect(GameMode.allCases.map(\.rawValue) == ["survival", "points"])
        #expect(ComingSoonMode.allCases.count == 3)
    }
}
