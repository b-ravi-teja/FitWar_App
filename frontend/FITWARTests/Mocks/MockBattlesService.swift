import Foundation

@testable import FITWAR

final class MockBattlesService: BattlesServiceProtocol, @unchecked Sendable {
    var listResult: Result<[Battle], Error> = .success([])
    var detailResult: Result<Battle, Error> = .failure(APIError.unknown("not configured"))
    var rivalsResult: Result<[BattleRival], Error> = .success([])
    var createResult: Result<Battle, Error> = .failure(APIError.unknown("not configured"))
    var acceptResult: Result<Battle, Error> = .failure(APIError.unknown("not configured"))
    var declineResult: Result<Battle, Error> = .failure(APIError.unknown("not configured"))
    var submitResult: Result<SubmitBattleEvidenceResponse, Error> = .failure(
        APIError.unknown("not configured")
    )

    private(set) var detailCallCount = 0
    private(set) var acceptCallCount = 0
    private(set) var declineCallCount = 0
    private(set) var submittedRequests: [SubmitVerificationRequest] = []
    private(set) var createdRequests: [CreateBattleRequest] = []
    private(set) var listedStatuses: [BattleStatus?] = []

    func fetchBattles(status: BattleStatus?) async throws -> [Battle] {
        listedStatuses.append(status)
        return try listResult.get()
    }

    func fetchBattle(id: UUID) async throws -> Battle {
        detailCallCount += 1
        return try detailResult.get()
    }

    func fetchRivals(groupId: UUID) async throws -> [BattleRival] {
        try rivalsResult.get()
    }

    func createBattle(_ request: CreateBattleRequest) async throws -> Battle {
        createdRequests.append(request)
        return try createResult.get()
    }

    func accept(battleId: UUID) async throws -> Battle {
        acceptCallCount += 1
        return try acceptResult.get()
    }

    func decline(battleId: UUID) async throws -> Battle {
        declineCallCount += 1
        return try declineResult.get()
    }

    func submitEvidence(
        battleId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitBattleEvidenceResponse {
        submittedRequests.append(request)
        return try submitResult.get()
    }
}

/// Battle DTOs, built so each test states only what it is about.
enum BattleFixtures {
    static let myId = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!
    static let theirId = UUID(uuidString: "22222222-2222-2222-2222-222222222222")!

    static func side(
        userId: UUID,
        name: String,
        status: BattleSideStatus,
        score: Decimal,
        daysCompleted: Int = 0,
        isMe: Bool
    ) -> BattleSide {
        BattleSide(
            userId: userId,
            displayName: name,
            status: status,
            score: score,
            daysCompleted: daysCompleted,
            isMe: isMe
        )
    }

    static func battle(
        id: UUID = UUID(),
        status: BattleStatus = .active,
        myStatus: BattleSideStatus = .active,
        theirStatus: BattleSideStatus = .active,
        myScore: Decimal = 0,
        theirScore: Decimal = 0,
        myDays: Int = 0,
        theirDays: Int = 0,
        dayIndex: Int = 1,
        durationDays: Int = 3,
        timeRemainingSeconds: Int = 86_400,
        winnerUserId: UUID? = nil,
        myOutcome: BattleOutcome? = nil,
        myXPAwarded: Int? = nil,
        completedAt: Date? = nil
    ) -> Battle {
        Battle(
            id: id,
            groupId: UUID(),
            status: status,
            activityType: .steps,
            targetValue: 10_000,
            unit: "steps",
            dayIndex: dayIndex,
            durationDays: durationDays,
            timezone: "Asia/Kolkata",
            startAt: Date(timeIntervalSince1970: 1_760_000_000),
            endAt: Date(timeIntervalSince1970: 1_760_259_200),
            completedAt: completedAt,
            timeRemainingSeconds: timeRemainingSeconds,
            sides: [
                side(
                    userId: myId, name: "Me", status: myStatus,
                    score: myScore, daysCompleted: myDays, isMe: true
                ),
                side(
                    userId: theirId, name: "Rival", status: theirStatus,
                    score: theirScore, daysCompleted: theirDays, isMe: false
                ),
            ],
            winnerUserId: winnerUserId,
            myOutcome: myOutcome,
            myXPAwarded: myXPAwarded
        )
    }

    static func rival(
        wins: Int = 0, losses: Int = 0, liveBattleId: UUID? = nil, name: String = "Rival"
    ) -> BattleRival {
        BattleRival(
            userId: theirId,
            displayName: name,
            winsAgainst: wins,
            lossesAgainst: losses,
            liveBattleId: liveBattleId
        )
    }

    static func evidenceResponse(battle: Battle) -> SubmitBattleEvidenceResponse {
        SubmitBattleEvidenceResponse(
            verification: VerificationFixtures.response(), battle: battle
        )
    }
}
