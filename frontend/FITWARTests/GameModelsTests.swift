import Foundation
import Testing

@testable import FITWAR

/// Decoding tests against **real server payload shapes**, captured from the running
/// backend rather than invented, so a contract drift breaks here instead of in the app.
struct GameDecodingTests {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONCoding.decoder.decode(type, from: Data(json.utf8))
    }

    @Test func decodesALeaderboard() throws {
        let board = try decode(Leaderboard.self, Self.leaderboardJSON)

        #expect(board.gameMode == "points")
        #expect(board.isFinal == false)
        #expect(board.entries.count == 2)
        #expect(board.entries[0].rank == 1)
        #expect(board.entries[0].displayName == "Alpha")
        #expect(board.entries[0].score == Decimal(string: "20000.00"))
        #expect(board.entries[0].isMe)
        #expect(board.entries[1].outcome == nil)
    }

    @Test func decodesFinalStandingsWithOutcomes() throws {
        let board = try decode(Leaderboard.self, Self.finalLeaderboardJSON)

        #expect(board.isFinal)
        #expect(board.entries[0].outcome == .won)
        #expect(board.entries[1].outcome == .lost)
        #expect(board.entries[0].status == .completed)
    }

    @Test func decodesAnEliminatedEntry() throws {
        let board = try decode(Leaderboard.self, Self.eliminatedLeaderboardJSON)

        #expect(board.entries[0].status == .eliminated)
        #expect(board.entries[0].outcome == .out)
    }

    @Test func decodesXPSummaryWithServerComputedLevel() throws {
        let xp = try decode(XPSummary.self, Self.xpJSON)

        #expect(xp.xpTotal == 60)
        #expect(xp.level == 1)
        #expect(xp.xpIntoLevel == 60)
        #expect(xp.xpToNextLevel == 440)
        #expect(xp.transactions.count == 2)
        #expect(xp.transactions[0].reason == .dailyCompletion)
        #expect(xp.transactions[1].reason == .streakBonus)
    }

    @Test func levelProgressUsesServerNumbersOnly() throws {
        let xp = try decode(XPSummary.self, Self.xpJSON)

        // 60 of a 500-XP level. Derived from the server's own into/to-next pair — the
        // client never recomputes the level itself.
        #expect(abs(xp.levelProgress - 0.12) < 0.0001)
    }

    @Test func decodesMyGameStateWithWarnings() throws {
        let state = try decode(MyChallengeGameState.self, Self.eliminatedStateJSON)

        #expect(state.status == .eliminated)
        #expect(state.outcome == .out)
        #expect(state.consecutiveMisses == 2)
        #expect(state.warnings.count == 2)
        #expect(state.eliminatedAt != nil)
        #expect(state.rank == 1)
    }

    @Test func decodesAHealthyGameState() throws {
        let state = try decode(MyChallengeGameState.self, Self.activeStateJSON)

        #expect(state.status == .active)
        #expect(state.outcome == nil)
        #expect(state.warnings.isEmpty)
        #expect(state.eliminatedAt == nil)
        #expect(state.currentStreak == 1)
    }

    @Test func decodesTheVerificationResolutionBreakdown() throws {
        let response = try decode(SubmitVerificationResponse.self, Self.verifyJSON)

        let resolution = try #require(response.resolution)
        #expect(resolution.xpAwarded == 60)
        #expect(resolution.completionXP == 50)
        #expect(resolution.streakBonusXP == 10)
        #expect(resolution.currentStreak == 2)
        #expect(resolution.scoreDelta == Decimal(string: "12000.00"))
    }

    @Test func aShortAttemptCarriesNoResolution() throws {
        /// Nothing was awarded, so the field is absent rather than zeroed — zeros would
        /// render as a real award of 0 XP.
        let response = try decode(SubmitVerificationResponse.self, Self.verifyNoResolutionJSON)

        #expect(response.resolution == nil)
        #expect(response.dayStatus == .pending)
    }

    // MARK: - Payloads (shapes captured from the running backend)

    private static let leaderboardJSON = """
    {"challenge_id":"36382dcd-a96b-40f6-9b2a-0dae8acf0233","game_mode":"points",
     "is_final":false,"entries":[
      {"rank":1,"user_id":"a1000000-0000-0000-0000-000000000001","display_name":"Alpha",
       "score":"20000.00","current_streak":1,"status":"active","outcome":null,"is_me":true},
      {"rank":2,"user_id":"a1000000-0000-0000-0000-000000000002","display_name":"Bravo",
       "score":"11000.00","current_streak":1,"status":"active","outcome":null,"is_me":false}]}
    """

    private static let finalLeaderboardJSON = """
    {"challenge_id":"36382dcd-a96b-40f6-9b2a-0dae8acf0233","game_mode":"points",
     "is_final":true,"entries":[
      {"rank":1,"user_id":"a1000000-0000-0000-0000-000000000001","display_name":"Alpha",
       "score":"20000.00","current_streak":1,"status":"completed","outcome":"won","is_me":true},
      {"rank":2,"user_id":"a1000000-0000-0000-0000-000000000002","display_name":"Bravo",
       "score":"11000.00","current_streak":1,"status":"completed","outcome":"lost","is_me":false}]}
    """

    private static let eliminatedLeaderboardJSON = """
    {"challenge_id":"1f4fe715-ae15-4350-b0db-ff3bf2ef1620","game_mode":"survival",
     "is_final":false,"entries":[
      {"rank":1,"user_id":"a1000000-0000-0000-0000-000000000001","display_name":"Alpha",
       "score":"0.00","current_streak":0,"status":"eliminated","outcome":"out","is_me":true}]}
    """

    private static let xpJSON = """
    {"xp_total":60,"level":1,"xp_into_level":60,"xp_to_next_level":440,"transactions":[
      {"id":"b1000000-0000-0000-0000-000000000001","amount":50,"reason":"daily_completion",
       "created_at":"2026-09-02T10:45:00.123456Z"},
      {"id":"b1000000-0000-0000-0000-000000000002","amount":10,"reason":"streak_bonus",
       "created_at":"2026-09-02T10:45:00.123456Z"}]}
    """

    private static let eliminatedStateJSON = """
    {"challenge_id":"1f4fe715-ae15-4350-b0db-ff3bf2ef1620","rank":1,"score":"0.00",
     "current_streak":0,"longest_streak":0,"consecutive_misses":2,"status":"eliminated",
     "outcome":"out","warnings":[
       {"challenge_day":"2026-08-30","reason":"missed_day","created_at":"2026-09-02T11:05:19.834307Z"},
       {"challenge_day":"2026-08-31","reason":"missed_day","created_at":"2026-09-02T11:05:19.834307Z"}],
     "eliminated_at":"2026-09-02T11:05:19.834307Z"}
    """

    private static let activeStateJSON = """
    {"challenge_id":"36382dcd-a96b-40f6-9b2a-0dae8acf0233","rank":1,"score":"20000.00",
     "current_streak":1,"longest_streak":1,"consecutive_misses":0,"status":"active",
     "outcome":null,"warnings":[],"eliminated_at":null}
    """

    private static let verifyJSON = """
    {"verification":{"id":"c1000000-0000-0000-0000-000000000001","provider":"apple_health",
      "metric":"steps","value":"12000.00","target":"10000.00","status":"verified",
      "reason_code":null,"source_timestamp":"2026-09-02T10:41:57Z",
      "verified_at":"2026-09-02T10:41:57Z"},
     "challenge_day":"2026-09-02","day_status":"completed",
     "deadline_at":"2026-09-02T18:30:00Z","idempotent_replay":false,
     "resolution":{"xp_awarded":60,"completion_xp":50,"streak_bonus_xp":10,
      "score_delta":"12000.00","current_streak":2}}
    """

    private static let verifyNoResolutionJSON = """
    {"verification":{"id":"c1000000-0000-0000-0000-000000000002","provider":"apple_health",
      "metric":"steps","value":"400.00","target":"10000.00","status":"inconclusive",
      "reason_code":"TARGET_NOT_MET","source_timestamp":"2026-09-02T10:41:57Z",
      "verified_at":null},
     "challenge_day":"2026-09-02","day_status":"pending",
     "deadline_at":"2026-09-02T18:30:00Z","idempotent_replay":false,"resolution":null}
    """
}

struct LeaderboardPresentationTests {
    private func entry(
        status: ParticipantStatus = .active,
        outcome: ParticipantOutcome? = nil,
        streak: Int = 0
    ) -> LeaderboardEntry {
        LeaderboardEntry(
            rank: 1,
            userId: UUID(),
            displayName: "Alpha",
            score: Decimal(100),
            currentStreak: streak,
            status: status,
            outcome: outcome,
            isMe: false
        )
    }

    @Test func showsEliminationFromServerStatus() {
        /// The client never infers "out" from a score — it reads the server's status.
        let label = LeaderboardRowPresentation.subLabel(
            for: entry(status: .eliminated, outcome: .out), isFinal: false
        )
        #expect(label == "ELIMINATED")
    }

    @Test func showsStreakWhileTheChallengeRuns() {
        let label = LeaderboardRowPresentation.subLabel(for: entry(streak: 4), isFinal: false)
        #expect(label == "4 DAY STREAK")
    }

    @Test func aSurvivorReadsAsStillInUntilTheChallengeCloses() {
        let running = LeaderboardRowPresentation.subLabel(
            for: entry(outcome: .won), isFinal: false
        )
        let finished = LeaderboardRowPresentation.subLabel(
            for: entry(outcome: .won), isFinal: true
        )
        #expect(running == "STILL IN")
        #expect(finished == "WON")
    }

    @Test func aDepartedParticipantIsLabelledLeft() {
        let label = LeaderboardRowPresentation.subLabel(
            for: entry(status: .left, outcome: .left), isFinal: true
        )
        #expect(label == "LEFT")
    }
}

// MARK: - Phase 8 hardening regressions

@MainActor
struct XPReasonForwardCompatibilityTests {
    private func decodeSummary(_ reason: String) throws -> XPSummary {
        let json = """
        {"xp_total": 150, "level": 1, "xp_into_level": 150, "xp_to_next_level": 350,
         "transactions": [
           {"id": "11111111-1111-1111-1111-111111111111", "amount": 100,
            "reason": "\(reason)", "created_at": "2026-09-03T10:00:00Z"}
         ]}
        """
        return try JSONCoding.decoder.decode(XPSummary.self, from: Data(json.utf8))
    }

    @Test func decodesTheBattleWinReasonPhase7Added() throws {
        /// The regression: the server started emitting `battle_win` and this enum did
        /// not know it, so every battle winner's XP screen failed to decode entirely.
        let summary = try decodeSummary("battle_win")

        #expect(summary.transactions[0].reason == .battleWin)
        #expect(summary.transactions[0].reason.displayName == "Battle win")
    }

    @Test func anUnrecognisedReasonDegradesToOneNeutralRow() throws {
        /// A future server value must cost one odd-looking row, never the whole screen.
        let summary = try decodeSummary("achievement_unlocked")

        #expect(summary.transactions[0].reason == .unknown)
        #expect(summary.transactions[0].amount == 100)
        #expect(summary.xpTotal == 150)
    }

    @Test func theKnownReasonsStillDecodeExactly() throws {
        #expect(try decodeSummary("daily_completion").transactions[0].reason == .dailyCompletion)
        #expect(try decodeSummary("streak_bonus").transactions[0].reason == .streakBonus)
    }

    @Test func everyReasonHasNonEmptyCopy() {
        for reason in [XPReason.dailyCompletion, .streakBonus, .battleWin, .unknown] {
            #expect(!reason.displayName.isEmpty)
        }
    }
}

@MainActor
struct GameModeDecodingTests {
    @Test func decodesTheBackingOneVOneModeWithoutFailingTheList() throws {
        /// 1v1 challenges are hidden from the challenge API, but a strict enum turns any
        /// leak into a whole list that will not load.
        let json = #"{"game_mode": "1v1"}"#
        struct Wrapper: Decodable { let gameMode: GameMode }

        let decoded = try JSONCoding.decoder.decode(Wrapper.self, from: Data(json.utf8))

        #expect(decoded.gameMode == .oneVOne)
    }

    @Test func theCreateFlowNeverOffers1v1() {
        /// `POST /groups/{id}/challenges` rejects it — a picker entry the server refuses
        /// is worse than one that isn't there.
        #expect(!GameMode.selectable.contains(.oneVOne))
        #expect(GameMode.selectable == [.survival, .points])
    }

    @Test func everyModeHasCopyForAllThreeSurfaces() {
        for mode in GameMode.allCases {
            #expect(!mode.displayName.isEmpty)
            #expect(!mode.tag.isEmpty)
            #expect(!mode.blurb.isEmpty)
        }
    }
}
