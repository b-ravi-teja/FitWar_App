import Foundation
@testable import FITWAR

final class MockGameService: GameServiceProtocol, @unchecked Sendable {
    var leaderboardResult: Result<Leaderboard, Error> = .failure(APIError.unknown("not configured"))
    var myStateResult: Result<MyChallengeGameState, Error> = .failure(
        APIError.unknown("not configured")
    )
    var xpResult: Result<XPSummary, Error> = .failure(APIError.unknown("not configured"))

    private(set) var leaderboardCallCount = 0

    func fetchLeaderboard(challengeId: UUID) async throws -> Leaderboard {
        leaderboardCallCount += 1
        return try leaderboardResult.get()
    }

    func fetchMyGameState(challengeId: UUID) async throws -> MyChallengeGameState {
        try myStateResult.get()
    }

    func fetchXPSummary() async throws -> XPSummary {
        try xpResult.get()
    }
}

enum GameFixtures {
    static func leaderboard(isFinal: Bool = false, entries: [LeaderboardEntry] = []) -> Leaderboard {
        Leaderboard(
            challengeId: UUID(),
            gameMode: "points",
            isFinal: isFinal,
            entries: entries.isEmpty ? [entry(rank: 1)] : entries
        )
    }

    static func entry(
        rank: Int,
        name: String = "Alpha",
        score: Decimal = 100,
        status: ParticipantStatus = .active,
        outcome: ParticipantOutcome? = nil,
        isMe: Bool = false
    ) -> LeaderboardEntry {
        LeaderboardEntry(
            rank: rank,
            userId: UUID(),
            displayName: name,
            score: score,
            currentStreak: 1,
            status: status,
            outcome: outcome,
            isMe: isMe
        )
    }

    static func resolution(
        xp: Int = 50, completion: Int = 50, bonus: Int = 0, streak: Int = 1
    ) -> DayResolution {
        DayResolution(
            xpAwarded: xp,
            completionXP: completion,
            streakBonusXP: bonus,
            scoreDelta: Decimal(12_000),
            currentStreak: streak
        )
    }

    static func xp(total: Int = 60, level: Int = 1) -> XPSummary {
        XPSummary(
            xpTotal: total,
            level: level,
            xpIntoLevel: total % 500,
            xpToNextLevel: 500 - (total % 500),
            transactions: []
        )
    }
}
