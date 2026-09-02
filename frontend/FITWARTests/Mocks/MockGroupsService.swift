import Foundation
@testable import FITWAR

/// Configurable stand-ins for the Groups/Challenges services, so ViewModel tests never
/// touch the network (Architecture §14 — no live server in unit tests).
final class MockGroupsService: GroupsServiceProtocol, @unchecked Sendable {
    var listResult: Result<[GroupSummary], Error> = .success([])
    var createResult: Result<GroupDetail, Error> = .failure(APIError.unknown("not configured"))
    var joinResult: Result<GroupDetail, Error> = .failure(APIError.unknown("not configured"))
    var fetchResult: Result<GroupDetail, Error> = .failure(APIError.unknown("not configured"))
    var membersResult: Result<[GroupMemberSummary], Error> = .success([])
    var activityResult: Result<[GroupActivityEntry], Error> = .success([])
    var leaveError: Error?

    private(set) var listCallCount = 0
    private(set) var createdNames: [String] = []
    private(set) var createdTimezones: [String] = []
    private(set) var joinedCodes: [String] = []
    private(set) var leaveCallCount = 0

    func listGroups() async throws -> [GroupSummary] {
        listCallCount += 1
        return try listResult.get()
    }

    func createGroup(name: String, timezone: String) async throws -> GroupDetail {
        createdNames.append(name)
        createdTimezones.append(timezone)
        return try createResult.get()
    }

    func joinGroup(code: String) async throws -> GroupDetail {
        joinedCodes.append(code)
        return try joinResult.get()
    }

    func fetchGroup(id: UUID) async throws -> GroupDetail {
        try fetchResult.get()
    }

    func fetchMembers(groupId: UUID) async throws -> [GroupMemberSummary] {
        try membersResult.get()
    }

    func fetchActivity(groupId: UUID) async throws -> [GroupActivityEntry] {
        try activityResult.get()
    }

    func leaveGroup(id: UUID) async throws {
        leaveCallCount += 1
        if let leaveError { throw leaveError }
    }
}

final class MockChallengesService: ChallengesServiceProtocol, @unchecked Sendable {
    var listMineResult: Result<[ChallengeSummary], Error> = .success([])
    var listForGroupResult: Result<[ChallengeSummary], Error> = .success([])
    var fetchResult: Result<ChallengeDetail, Error> = .failure(APIError.unknown("not configured"))
    var createResult: Result<ChallengeDetail, Error> = .failure(APIError.unknown("not configured"))
    var joinResult: Result<ChallengeDetail, Error> = .failure(APIError.unknown("not configured"))
    var leaveError: Error?
    var todayResult: Result<DailyProgress, Error> = .failure(APIError.unknown("not configured"))

    private(set) var requestedStatuses: [ChallengeStatus?] = []
    private(set) var createdRequests: [CreateChallengeRequest] = []
    private(set) var createdGroupIds: [UUID] = []
    private(set) var joinCallCount = 0
    private(set) var leaveCallCount = 0
    private(set) var fetchCallCount = 0

    func listMyChallenges(status: ChallengeStatus?) async throws -> [ChallengeSummary] {
        requestedStatuses.append(status)
        return try listMineResult.get()
    }

    func listGroupChallenges(groupId: UUID) async throws -> [ChallengeSummary] {
        try listForGroupResult.get()
    }

    func fetchChallenge(id: UUID) async throws -> ChallengeDetail {
        fetchCallCount += 1
        return try fetchResult.get()
    }

    func createChallenge(
        groupId: UUID, request: CreateChallengeRequest
    ) async throws -> ChallengeDetail {
        createdGroupIds.append(groupId)
        createdRequests.append(request)
        return try createResult.get()
    }

    func joinChallenge(id: UUID) async throws -> ChallengeDetail {
        joinCallCount += 1
        return try joinResult.get()
    }

    func leaveChallenge(id: UUID) async throws {
        leaveCallCount += 1
        if let leaveError { throw leaveError }
    }

    func fetchTodayProgress(challengeId: UUID) async throws -> DailyProgress {
        try todayResult.get()
    }
}

/// Builders for the DTOs these tests need, so each test states only what it cares about.
enum Fixture {
    static func groupSummary(
        id: UUID = UUID(),
        name: String = "KITS FITNESS WAR",
        memberCount: Int = 3,
        activeChallengeCount: Int = 1
    ) -> GroupSummary {
        GroupSummary(
            id: id,
            name: name,
            timezone: "Asia/Kolkata",
            memberCount: memberCount,
            activeChallengeCount: activeChallengeCount
        )
    }

    static func groupDetail(
        id: UUID = UUID(),
        name: String = "KITS FITNESS WAR",
        joinCode: String = "K7-XR9",
        myRole: GroupRole = .owner,
        memberCount: Int = 3
    ) -> GroupDetail {
        GroupDetail(
            id: id,
            name: name,
            timezone: "Asia/Kolkata",
            privacy: "invite",
            ownerId: UUID(),
            memberCount: memberCount,
            activeChallengeCount: 1,
            createdAt: Date(timeIntervalSince1970: 1_760_000_000),
            joinCode: joinCode,
            myRole: myRole
        )
    }

    static func member(
        userId: UUID = UUID(),
        displayName: String = "Ravi",
        role: GroupRole = .member,
        activeChallengeCount: Int = 0
    ) -> GroupMemberSummary {
        GroupMemberSummary(
            userId: userId,
            displayName: displayName,
            role: role,
            status: .active,
            joinedAt: Date(timeIntervalSince1970: 1_760_000_000),
            activeChallengeCount: activeChallengeCount
        )
    }

    static func challengeSummary(
        id: UUID = UUID(),
        name: String = "30 DAY STEP WAR",
        status: ChallengeStatus = .active,
        dayIndex: Int = 6,
        durationDays: Int = 30,
        participantCount: Int = 8
    ) -> ChallengeSummary {
        ChallengeSummary(
            id: id,
            groupId: UUID(),
            name: name,
            activityType: .steps,
            gameMode: .survival,
            status: status,
            targetValue: 10_000,
            unit: "steps",
            dayIndex: dayIndex,
            durationDays: durationDays,
            participantCount: participantCount,
            myStatus: .active
        )
    }

    static func challengeDetail(
        id: UUID = UUID(),
        status: ChallengeStatus = .active,
        myStatus: ParticipantStatus? = .active,
        gameMode: GameMode = .survival,
        participants: [ChallengeParticipantSummary] = []
    ) -> ChallengeDetail {
        ChallengeDetail(
            id: id,
            groupId: UUID(),
            groupName: "KITS FITNESS WAR",
            creatorId: UUID(),
            name: "30 DAY STEP WAR",
            activityType: .steps,
            gameMode: gameMode,
            verificationMethod: .appleHealth,
            status: status,
            targetValue: 10_000,
            unit: "steps",
            timezone: "Asia/Kolkata",
            startAt: Date(timeIntervalSince1970: 1_760_000_000),
            endAt: Date(timeIntervalSince1970: 1_762_592_000),
            dayIndex: 6,
            durationDays: 30,
            participantCount: participants.count,
            participantLimit: nil,
            failureRule: gameMode == .survival
                ? "MISS TWICE → ELIMINATED"
                : "NO ELIMINATION · HIGHEST TOTAL WINS",
            myStatus: myStatus,
            participants: participants
        )
    }

    static func participant(
        userId: UUID = UUID(),
        displayName: String = "Ravi",
        status: ParticipantStatus = .active,
        rank: Int = 1
    ) -> ChallengeParticipantSummary {
        ChallengeParticipantSummary(
            userId: userId,
            displayName: displayName,
            status: status,
            outcome: nil,
            currentScore: 0,
            currentStreak: 0,
            rank: rank,
            joinedAt: Date(timeIntervalSince1970: 1_760_000_000)
        )
    }

    static func dailyProgress(status: DailyProgressStatus = .pending) -> DailyProgress {
        DailyProgress(
            challengeDay: Date(timeIntervalSince1970: 1_760_000_000),
            dayIndex: 6,
            status: status,
            target: 10_000,
            unit: "steps",
            deadlineAt: Date(timeIntervalSince1970: 1_760_086_400),
            completedAt: nil
        )
    }
}
