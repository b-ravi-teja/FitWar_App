import Foundation
import Testing

@testable import FITWAR

/// A session manager holding a real access token, as the app does whenever a battle
/// screen is on screen.
@MainActor
private func makeAuthenticatedSession() async -> SessionManager {
    let auth = MockAuthService()
    let keychain = MockKeychainStore()
    let manager = SessionManager(
        authService: auth,
        keychain: keychain,
        apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
    )
    auth.loginResult = .success(
        AuthenticatedSession(
            userId: BattleFixtures.myId,
            accessToken: TestJWT.make(subject: BattleFixtures.myId),
            refreshToken: "refresh",
            expiresIn: 900
        )
    )
    // Actually sign in — merely configuring the mock leaves `accessToken` nil, and
    // `connectRealtime()` returns early without a token.
    try? await manager.login(email: "me@example.com", password: "hunter2222")
    return manager
}

@MainActor
private func makeSession() -> SessionManager {
    SessionManager(
        authService: MockAuthService(),
        keychain: MockKeychainStore(),
        apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
    )
}

// MARK: - Decoding

@MainActor
struct BattleDecodingTests {
    private func decode(_ json: String) throws -> Battle {
        try JSONCoding.decoder.decode(Battle.self, from: Data(json.utf8))
    }

    private let live = """
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "group_id": "33333333-3333-3333-3333-333333333333",
      "status": "active",
      "activity_type": "steps",
      "target_value": "10000.00",
      "unit": "steps",
      "day_index": 2,
      "duration_days": 7,
      "timezone": "Asia/Kolkata",
      "start_at": "2026-09-01T18:30:00Z",
      "end_at": "2026-09-08T18:30:00Z",
      "completed_at": null,
      "time_remaining_seconds": 432000,
      "sides": [
        {"user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "display_name": "Me",
         "status": "active", "score": "24000.00", "days_completed": 2, "is_me": true},
        {"user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "display_name": "Rival",
         "status": "active", "score": "12000.00", "days_completed": 1, "is_me": false}
      ],
      "winner_user_id": null,
      "my_outcome": null,
      "my_xp_awarded": null
    }
    """

    @Test func decodesTheServersLiveBattleShape() throws {
        let battle = try decode(live)

        #expect(battle.status == .active)
        #expect(battle.dayIndex == 2)
        #expect(battle.me?.score == 24_000)
        #expect(battle.opponent?.displayName == "Rival")
    }

    @Test func decimalsArriveAsStringsWithoutFloatingPointDrift() throws {
        /// The column is `NUMERIC(12,2)`; a JSON float would round-trip imprecisely.
        let battle = try decode(live)

        #expect(battle.targetValue == Decimal(string: "10000.00"))
    }

    @Test func anUnfinishedBattleHasNoWinnerAndNoOutcome() throws {
        let battle = try decode(live)

        #expect(battle.winnerUserId == nil)
        #expect(battle.myOutcome == nil)
        #expect(battle.isFinalized == false)
    }

    /// A finished battle exactly as the server sends it. Written out in full rather than
    /// string-substituted from `live`: the previous version replaced *every*
    /// `"status": "active"`, including both sides', producing a `BattleSideStatus` value
    /// the enum correctly has no case for — so the test failed on its own fixture rather
    /// than on the behaviour it meant to check.
    private let finalized = """
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "group_id": "33333333-3333-3333-3333-333333333333",
      "status": "completed",
      "activity_type": "steps",
      "target_value": "10000.00",
      "unit": "steps",
      "day_index": 7,
      "duration_days": 7,
      "timezone": "Asia/Kolkata",
      "start_at": "2026-09-01T18:30:00Z",
      "end_at": "2026-09-08T18:30:00Z",
      "completed_at": "2026-09-08T18:31:00Z",
      "time_remaining_seconds": 0,
      "sides": [
        {"user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "display_name": "Me",
         "status": "won", "score": "24000.00", "days_completed": 7, "is_me": true},
        {"user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "display_name": "Rival",
         "status": "lost", "score": "12000.00", "days_completed": 5, "is_me": false}
      ],
      "winner_user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "my_outcome": "won",
      "my_xp_awarded": 100
    }
    """

    @Test func decodesTheFinalizedShapeIncludingTheLedgerAward() throws {
        let battle = try decode(finalized)

        #expect(battle.myOutcome == .won)
        #expect(battle.myXPAwarded == 100)
        #expect(battle.completedAt != nil)
        #expect(battle.isFinalized)
        #expect(battle.me?.status == .won)
        #expect(battle.opponent?.status == .lost)
    }

    @Test func theVersusSplitIsPresentationOnly() throws {
        /// It renders two server scores as a ratio; nothing reads it to decide anything.
        let battle = try decode(live)

        #expect(abs(battle.myShareOfScore - (2.0 / 3.0)) < 0.001)
    }

    @Test func aScorelessBattleSplitsTheBarEvenly() {
        let battle = BattleFixtures.battle(myScore: 0, theirScore: 0)

        #expect(battle.myShareOfScore == 0.5)
    }
}

// MARK: - Battles list

@MainActor
struct BattlesListViewModelTests {
    private func makeSUT() -> (BattlesListViewModel, MockBattlesService) {
        let battles = MockBattlesService()
        let sut = BattlesListViewModel(
            battles: battles, groups: MockGroupsService(), sessionManager: makeSession()
        )
        return (sut, battles)
    }

    @Test func separatesInvitationsFromBattlesAwaitingTheOpponent() async {
        /// A pending battle is an invitation only when *I* am the invited side. The
        /// challenger's own pending battle is waiting on someone else.
        let (sut, battles) = makeSUT()
        battles.listResult = .success([
            BattleFixtures.battle(status: .pending, myStatus: .invited, theirStatus: .accepted),
            BattleFixtures.battle(status: .pending, myStatus: .accepted, theirStatus: .invited),
        ])

        await sut.load()

        #expect(sut.invitations.count == 1)
        #expect(sut.awaitingOpponent.count == 1)
    }

    @Test func surfacesTheOneLiveBattle() async {
        let (sut, battles) = makeSUT()
        battles.listResult = .success([
            BattleFixtures.battle(status: .completed, myOutcome: .won),
            BattleFixtures.battle(status: .active),
        ])

        await sut.load()

        #expect(sut.live?.status == .active)
    }

    @Test func historyHoldsFinishedAndCancelledBattles() async {
        let (sut, battles) = makeSUT()
        battles.listResult = .success([
            BattleFixtures.battle(status: .completed, myOutcome: .lost),
            BattleFixtures.battle(status: .cancelled),
            BattleFixtures.battle(status: .active),
        ])

        await sut.load()

        #expect(sut.history.count == 2)
    }

    @Test func acceptingRereadsTheListRatherThanPatchingItLocally() async {
        /// Accepting changes more than the row that was tapped, and the server is the
        /// record — so the whole list is re-read.
        let (sut, battles) = makeSUT()
        let pending = BattleFixtures.battle(status: .pending, myStatus: .invited)
        battles.listResult = .success([pending])
        battles.acceptResult = .success(BattleFixtures.battle(id: pending.id, status: .active))
        await sut.load()

        battles.listResult = .success([BattleFixtures.battle(id: pending.id, status: .active)])
        await sut.accept(pending)

        #expect(battles.acceptCallCount == 1)
        #expect(sut.live != nil)
        #expect(sut.invitations.isEmpty)
    }

    @Test func decliningIsReportedThroughTheServersReply() async {
        let (sut, battles) = makeSUT()
        let pending = BattleFixtures.battle(status: .pending, myStatus: .invited)
        battles.listResult = .success([pending])
        battles.declineResult = .success(
            BattleFixtures.battle(id: pending.id, status: .cancelled, myStatus: .declined)
        )
        await sut.load()
        battles.listResult = .success([
            BattleFixtures.battle(id: pending.id, status: .cancelled, myStatus: .declined)
        ])

        await sut.decline(pending)

        #expect(battles.declineCallCount == 1)
        #expect(sut.history.count == 1)
    }

    @Test func networkFailureIsItsOwnState() async {
        let (sut, battles) = makeSUT()
        battles.listResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func unauthorizedIsItsOwnState() async {
        let (sut, battles) = makeSUT()
        battles.listResult = .failure(
            APIError.server(status: 401, code: "UNAUTHENTICATED", detail: "nope")
        )

        await sut.load()

        #expect(sut.state == .unauthorized)
    }

    @Test func anEmptyListIsLoadedNotAnError() async {
        let (sut, battles) = makeSUT()
        battles.listResult = .success([])

        await sut.load()

        #expect(sut.state == .loaded([]))
        #expect(sut.hasAnything == false)
    }

    @Test func aRefusedActionShowsProductCopyNotTheServerSentence() async {
        let (sut, battles) = makeSUT()
        let pending = BattleFixtures.battle(status: .pending, myStatus: .invited)
        battles.listResult = .success([pending])
        battles.acceptResult = .failure(
            APIError.server(status: 409, code: "NOT_INVITED", detail: "raw server text")
        )
        await sut.load()

        await sut.accept(pending)

        #expect(sut.actionError == "This invitation isn't yours to answer.")
    }
}

// MARK: - Battle detail

@MainActor
struct BattleDetailViewModelTests {
    private func makeSUT() async -> (
        BattleDetailViewModel, MockBattlesService, MockHealthKitService, MockRealtimeClient
    ) {
        let battles = MockBattlesService()
        let health = MockHealthKitService()
        let realtime = MockRealtimeClient()
        let sut = BattleDetailViewModel(
            battleId: UUID(),
            battles: battles,
            health: health,
            realtime: realtime,
            // An *authenticated* session: `connectRealtime()` needs an access token for
            // the socket handshake, and a signed-out session manager makes it return
            // before opening anything — which silently turned the realtime assertions
            // below into no-ops.
            sessionManager: await makeAuthenticatedSession()
        )
        return (sut, battles, health, realtime)
    }

    // ---- Phase mapping

    @Test func anInvitationToMeIsDistinctFromOneIAmWaitingOn() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .pending, myStatus: .invited)
        )
        await sut.load()
        guard case .invited = sut.phase else {
            Issue.record("expected invited, got \(sut.phase)")
            return
        }

        battles.detailResult = .success(
            BattleFixtures.battle(status: .pending, myStatus: .accepted, theirStatus: .invited)
        )
        await sut.reload()
        guard case .awaitingOpponent = sut.phase else {
            Issue.record("expected awaitingOpponent, got \(sut.phase)")
            return
        }
    }

    @Test func todaysDayIsDoneOnlyWhenBankedDaysReachTheCurrentDay() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .active, myDays: 1, dayIndex: 2)
        )

        await sut.load()

        guard case .active(_, let mineIsDone) = sut.phase else {
            Issue.record("expected active, got \(sut.phase)")
            return
        }
        #expect(mineIsDone == false)
    }

    @Test func victoryComesFromTheServersOutcomeNotAScoreComparison() async {
        /// The decisive test for §22. The caller's score is *lower*, and the server says
        /// they won — the screen must render Victory. A client that compared scores
        /// would disagree with the ledger that paid out.
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(
                status: .completed,
                myStatus: .won,
                theirStatus: .lost,
                myScore: 100,
                theirScore: 9_999,
                winnerUserId: BattleFixtures.myId,
                myOutcome: .won,
                myXPAwarded: 100
            )
        )

        await sut.load()

        guard case .victory = sut.phase else {
            Issue.record("expected victory, got \(sut.phase)")
            return
        }
    }

    @Test func defeatAlsoComesFromTheServerEvenWithTheHigherScoreInHand() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(
                status: .completed,
                myStatus: .lost,
                theirStatus: .won,
                myScore: 9_999,
                theirScore: 100,
                winnerUserId: BattleFixtures.theirId,
                myOutcome: .lost
            )
        )

        await sut.load()

        guard case .defeat = sut.phase else {
            Issue.record("expected defeat, got \(sut.phase)")
            return
        }
    }

    @Test func aCompletedBattleWithNoOutcomeNeverGuessesAWinner() async {
        /// Rather than inventing a verdict from the scores it happens to hold.
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .completed, myScore: 9_999, theirScore: 1, myOutcome: nil)
        )

        await sut.load()

        guard case .active = sut.phase else {
            Issue.record("expected no verdict, got \(sut.phase)")
            return
        }
    }

    @Test func aCancelledBattleIsItsOwnState() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .cancelled, myStatus: .declined)
        )

        await sut.load()

        guard case .cancelled = sut.phase else {
            Issue.record("expected cancelled, got \(sut.phase)")
            return
        }
    }

    // ---- Actions

    @Test func acceptingAppliesTheServersReply() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .pending, myStatus: .invited)
        )
        battles.acceptResult = .success(BattleFixtures.battle(status: .active))
        await sut.load()

        await sut.accept()

        #expect(battles.acceptCallCount == 1)
        guard case .active = sut.phase else {
            Issue.record("expected active, got \(sut.phase)")
            return
        }
    }

    @Test func decliningAppliesTheServersReply() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .pending, myStatus: .invited)
        )
        battles.declineResult = .success(
            BattleFixtures.battle(status: .cancelled, myStatus: .declined)
        )
        await sut.load()

        await sut.decline()

        guard case .cancelled = sut.phase else {
            Issue.record("expected cancelled, got \(sut.phase)")
            return
        }
    }

    // ---- Evidence

    @Test func evidenceIsReadOverTheServersWindowNotTheDeviceDay() async {
        /// The battle day belongs to the battle's frozen timezone (§11), which is
        /// frequently not the device's.
        let (sut, battles, health, _) = await makeSUT()
        let battle = BattleFixtures.battle(status: .active)
        battles.detailResult = .success(battle)
        health.evidenceResult = .success(VerificationFixtures.evidence())
        battles.submitResult = .success(BattleFixtures.evidenceResponse(battle: battle))
        await sut.load()

        await sut.submitTodaysEvidence()

        #expect(health.readWindows.count == 1)
        #expect(health.readWindows[0].start == battle.startAt)
        #expect(health.readWindows[0].end <= battle.endAt)
        #expect(health.readActivities == [.steps])
    }

    @Test func theSubmissionCarriesEvidenceAndNothingElse() async {
        /// No score, no winner, no XP — the request type has no field for any of them.
        let (sut, battles, health, _) = await makeSUT()
        let battle = BattleFixtures.battle(status: .active)
        battles.detailResult = .success(battle)
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "12000"))
        battles.submitResult = .success(BattleFixtures.evidenceResponse(battle: battle))
        await sut.load()

        await sut.submitTodaysEvidence()

        #expect(battles.submittedRequests.count == 1)
        let request = battles.submittedRequests[0]
        #expect(request.provider == .appleHealth)
        #expect(request.evidence.value == "12000")
        #expect(request.evidence.unit == "steps")
    }

    @Test func aSubmissionThatEndsTheBattleRendersTheResultImmediately() async {
        /// The reply carries the finalized battle, so no extra round trip is needed.
        let (sut, battles, health, _) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        health.evidenceResult = .success(VerificationFixtures.evidence())
        battles.submitResult = .success(
            BattleFixtures.evidenceResponse(
                battle: BattleFixtures.battle(
                    status: .completed,
                    myStatus: .won,
                    theirStatus: .lost,
                    winnerUserId: BattleFixtures.myId,
                    myOutcome: .won,
                    myXPAwarded: 100
                )
            )
        )
        await sut.load()

        await sut.submitTodaysEvidence()

        guard case .victory = sut.phase else {
            Issue.record("expected victory, got \(sut.phase)")
            return
        }
    }

    @Test func lateEvidenceIsReportedAsARefusalNotSilentlySwallowed() async {
        let (sut, battles, health, _) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        health.evidenceResult = .success(VerificationFixtures.evidence())
        battles.submitResult = .failure(
            APIError.server(status: 409, code: "BATTLE_NOT_ACTIVE", detail: "over")
        )
        await sut.load()

        await sut.submitTodaysEvidence()

        #expect(sut.actionError == "This battle isn't running, so it can't take evidence.")
    }

    @Test func aHealthKitFailureNeverLeaksFrameworkText() async {
        let (sut, battles, health, _) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        health.evidenceResult = .failure(HealthKitError.queryFailed)
        await sut.load()

        await sut.submitTodaysEvidence()

        let message = sut.actionError?.lowercased() ?? ""
        #expect(!message.isEmpty)
        #expect(!message.contains("healthkit"))
        #expect(!message.contains("nserror"))
        #expect(battles.submittedRequests.isEmpty)
    }

    @Test func evidenceIsNeverSubmittedForAPendingBattle() async {
        let (sut, battles, health, _) = await makeSUT()
        battles.detailResult = .success(
            BattleFixtures.battle(status: .pending, myStatus: .invited)
        )
        health.evidenceResult = .success(VerificationFixtures.evidence())
        await sut.load()

        await sut.submitTodaysEvidence()

        #expect(battles.submittedRequests.isEmpty)
    }

    // ---- Errors

    @Test func networkFailureAndServerErrorAreDistinctPhases() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .failure(APIError.noConnection)
        await sut.load()
        #expect(sut.phase == .networkFailure)

        battles.detailResult = .failure(
            APIError.server(status: 500, code: "INTERNAL_ERROR", detail: "boom")
        )
        await sut.reload()
        guard case .serverError = sut.phase else {
            Issue.record("expected serverError, got \(sut.phase)")
            return
        }
    }

    @Test func aBattleTheCallerCannotSeeIsAnError() async {
        let (sut, battles, _, _) = await makeSUT()
        battles.detailResult = .failure(
            APIError.server(status: 404, code: "BATTLE_NOT_FOUND", detail: "gone")
        )

        await sut.load()

        guard case .serverError = sut.phase else {
            Issue.record("expected serverError, got \(sut.phase)")
            return
        }
    }

    // ---- Realtime

    @Test func aBattleEventTriggersARestReadRatherThanCarryingState() async {
        /// The payloads carry no scores by design; the only correct response is to
        /// re-read. This is also what makes a duplicated event harmless.
        let (sut, battles, _, realtime) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        realtime.eventsToEmit = [
            .battleChanged(battleId: UUID()),
            .battleChanged(battleId: UUID()),
        ]
        await sut.load()
        let before = battles.detailCallCount

        sut.connectRealtime()
        await Task.yield()
        try? await Task.sleep(for: .milliseconds(60))

        #expect(realtime.battleConnectCount == 1)
        #expect(battles.detailCallCount > before)
    }

    @Test func aCompletionEventStillGoesThroughRestForTheVerdict() async {
        let (sut, battles, _, realtime) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        await sut.load()
        battles.detailResult = .success(
            BattleFixtures.battle(
                status: .completed,
                myStatus: .lost,
                theirStatus: .won,
                winnerUserId: BattleFixtures.theirId,
                myOutcome: .lost
            )
        )
        realtime.eventsToEmit = [
            .battleCompleted(battleId: UUID(), winnerUserId: BattleFixtures.myId)
        ]

        sut.connectRealtime()
        await Task.yield()
        try? await Task.sleep(for: .milliseconds(60))

        // The event named *me* as the winner; REST says otherwise, and REST wins.
        guard case .defeat = sut.phase else {
            Issue.record("expected defeat from REST, got \(sut.phase)")
            return
        }
    }

    @Test func aDroppedSocketLeavesTheScreenWorkingOverRest() async {
        /// The mock's stream finishes immediately, which models the socket dropping.
        let (sut, battles, _, realtime) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        await sut.load()

        sut.connectRealtime()
        await Task.yield()
        try? await Task.sleep(for: .milliseconds(60))

        #expect(sut.isLive == false)
        await sut.reload()
        guard case .active = sut.phase else {
            Issue.record("expected active after REST reconcile, got \(sut.phase)")
            return
        }
        _ = realtime
    }

    @Test func reconnectingDoesNotOpenASecondSocket() async {
        let (sut, battles, _, realtime) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        await sut.load()

        sut.connectRealtime()
        sut.connectRealtime()
        await Task.yield()

        #expect(realtime.battleConnectCount <= 1)
    }

    @Test func disconnectingReleasesTheSocket() async {
        let (sut, battles, _, realtime) = await makeSUT()
        battles.detailResult = .success(BattleFixtures.battle(status: .active))
        await sut.load()
        sut.connectRealtime()

        sut.disconnectRealtime()

        #expect(realtime.disconnectCount == 1)
        #expect(sut.isLive == false)
    }
}

// MARK: - Realtime parsing

struct BattleRealtimeEventTests {
    @Test func parsesTheThreeBattleEventsTheServerPublishes() {
        let battleId = UUID()
        let base: [String: Any] = ["battle_id": battleId.uuidString]

        #expect(
            RealtimeEvent.parse(base.merging(["type": "battle_invited"]) { _, new in new })
                == .battleInvited(battleId: battleId)
        )
        #expect(
            RealtimeEvent.parse(base.merging(["type": "battle_status_changed"]) { _, new in new })
                == .battleChanged(battleId: battleId)
        )
        #expect(
            RealtimeEvent.parse(base.merging(["type": "battle_progress"]) { _, new in new })
                == .battleChanged(battleId: battleId)
        )
    }

    @Test func parsesTheWinnerOffACompletionEvent() {
        let battleId = UUID()
        let winner = UUID()

        let event = RealtimeEvent.parse([
            "type": "battle_completed",
            "battle_id": battleId.uuidString,
            "winner_user_id": winner.uuidString,
        ])

        #expect(event == .battleCompleted(battleId: battleId, winnerUserId: winner))
    }

    @Test func anUnknownEventTypeIsIgnoredRatherThanFatal() {
        /// A server that adds an event must never break an older client.
        #expect(RealtimeEvent.parse(["type": "battle_teleported"]) == .unknown)
    }

    @Test func aBattleEventWithoutAnIdIsIgnored() {
        #expect(RealtimeEvent.parse(["type": "battle_completed"]) == .unknown)
    }
}

// MARK: - Create

@MainActor
struct CreateBattleViewModelTests {
    private func makeSUT() -> (CreateBattleViewModel, MockBattlesService, MockGroupsService) {
        let battles = MockBattlesService()
        let groups = MockGroupsService()
        let sut = CreateBattleViewModel(
            battles: battles, groups: groups, sessionManager: makeSession()
        )
        return (sut, battles, groups)
    }

    @Test func onlyOffersActivitiesHealthCanMeasure() {
        /// A battle verifies automatically, and HealthKit has no push-up count — so
        /// push-ups are not offered rather than offered and refused.
        #expect(!CreateBattleViewModel.selectableActivities.contains(.pushups))
        #expect(CreateBattleViewModel.selectableActivities.contains(.steps))
    }

    @Test func loadsSquadsAndSelectsTheFirstOne() async {
        let (sut, battles, groups) = await makeSUT()
        let group = Fixture.groupSummary(name: "KITS")
        groups.listResult = .success([group])
        battles.rivalsResult = .success([BattleFixtures.rival()])

        await sut.load()

        #expect(sut.selectedGroupId == group.id)
        #expect(sut.rivals.count == 1)
    }

    @Test func anEmptyTargetSendsNothingSoTheServerFillsInItsDefault() async {
        let (sut, battles, groups) = await makeSUT()
        groups.listResult = .success([Fixture.groupSummary()])
        battles.rivalsResult = .success([BattleFixtures.rival()])
        battles.createResult = .success(BattleFixtures.battle(status: .pending))
        await sut.load()
        sut.targetText = "   "

        await sut.challenge(BattleFixtures.rival())

        #expect(battles.createdRequests[0].targetValue == nil)
    }

    @Test func atypedTargetIsSentThrough() async {
        let (sut, battles, groups) = await makeSUT()
        groups.listResult = .success([Fixture.groupSummary()])
        battles.rivalsResult = .success([BattleFixtures.rival()])
        battles.createResult = .success(BattleFixtures.battle(status: .pending))
        await sut.load()
        sut.targetText = "15000"
        sut.durationDays = 14

        await sut.challenge(BattleFixtures.rival())

        #expect(battles.createdRequests[0].targetValue == "15000")
        #expect(battles.createdRequests[0].durationDays == 14)
    }

    @Test func aDuplicateChallengeIsExplainedInProductCopy() async {
        let (sut, battles, groups) = await makeSUT()
        groups.listResult = .success([Fixture.groupSummary()])
        battles.rivalsResult = .success([BattleFixtures.rival()])
        battles.createResult = .failure(
            APIError.server(
                status: 409, code: "ALREADY_PENDING_WITH_USER", detail: "raw"
            )
        )
        await sut.load()

        await sut.challenge(BattleFixtures.rival())

        #expect(sut.actionError == "You already have a battle running with this player.")
        #expect(sut.createdBattle == nil)
    }

    @Test func aRivalAlreadyInABattleIsMarkedByTheServerNotInferredHere() async {
        let (sut, battles, groups) = await makeSUT()
        groups.listResult = .success([Fixture.groupSummary()])
        battles.rivalsResult = .success([BattleFixtures.rival(liveBattleId: UUID())])

        await sut.load()

        #expect(sut.rivals[0].liveBattleId != nil)
    }

    @Test func headToHeadRecordsComeFromTheServer() async {
        let (sut, battles, groups) = await makeSUT()
        groups.listResult = .success([Fixture.groupSummary()])
        battles.rivalsResult = .success([BattleFixtures.rival(wins: 3, losses: 1)])

        await sut.load()

        #expect(sut.rivals[0].record == "3W – 1L")
    }
}
