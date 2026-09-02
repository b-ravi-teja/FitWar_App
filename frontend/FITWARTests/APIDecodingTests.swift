import Foundation
import Testing
@testable import FITWAR

/// Decoding tests against payloads copied verbatim from the running backend.
///
/// These exist because of a real bug caught in Phase 3 simulator validation: the server
/// returned `201 Created` for a new challenge and the app showed a generic failure,
/// because Pydantic serializes `Decimal` as a JSON *string* and Swift's `Decimal`
/// decoder only accepts a number. Nothing in the ViewModel tests could have caught it —
/// they build DTOs in memory rather than decoding real JSON.
struct APIDecodingTests {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONCoding.decoder.decode(type, from: Data(json.utf8))
    }

    @Test func decodesDecimalSentAsAString() throws {
        let challenge = try decode(ChallengeSummary.self, Self.challengeSummaryJSON)

        #expect(challenge.targetValue == Decimal(string: "10000.00"))
        #expect(challenge.targetLabel == "10,000 STEPS")
    }

    @Test func decodesDecimalSentAsANumber() throws {
        // Accepted too, so the client survives the field ever being emitted unquoted.
        let json = Self.challengeSummaryJSON.replacingOccurrences(
            of: "\"target_value\": \"10000.00\"", with: "\"target_value\": 10000.00"
        )
        let challenge = try decode(ChallengeSummary.self, json)

        #expect(challenge.targetValue == Decimal(string: "10000.00"))
    }

    @Test func decodesTimestampsWithPostgresMicrosecondPrecision() throws {
        let group = try decode(GroupDetail.self, Self.groupDetailJSON)

        #expect(group.name == "KITS FITNESS WAR")
        #expect(group.joinCode == "K7-XR9")
        #expect(group.myRole == .owner)
        // `.iso8601` alone rejects fractional seconds, which every Postgres timestamp has.
        #expect(abs(group.createdAt.timeIntervalSince1970 - 1_788_331_613.300223) < 0.001)
    }

    @Test func decodesABareCalendarDay() throws {
        let progress = try decode(DailyProgress.self, Self.dailyProgressJSON)

        #expect(progress.status == .pending)
        #expect(progress.dayIndex == 1)
        #expect(progress.target == Decimal(string: "10000.00"))

        // Parsed at UTC midnight so the server's already-resolved challenge day never
        // shifts because the device sits in another timezone.
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let components = calendar.dateComponents(
            [.year, .month, .day], from: progress.challengeDay
        )
        #expect(components.year == 2026)
        #expect(components.month == 9)
        #expect(components.day == 2)
    }

    @Test func decodesAFullChallengeDetailWithParticipants() throws {
        let detail = try decode(ChallengeDetail.self, Self.challengeDetailJSON)

        #expect(detail.name == "30 DAY STEPS WAR")
        #expect(detail.gameMode == .survival)
        #expect(detail.verificationMethod == .appleHealth)
        #expect(detail.failureRule == "MISS TWICE → ELIMINATED")
        #expect(detail.myStatus == .active)
        #expect(detail.participants.count == 1)
        #expect(detail.participants[0].currentScore == 0)
        #expect(detail.headerMeta == "DAY 1 / 30 · MISS TWICE → ELIMINATED")
    }

    @Test func decodesGroupSummaryList() throws {
        let groups = try decode([GroupSummary].self, Self.groupListJSON)

        #expect(groups.count == 1)
        #expect(groups[0].metaLine == "3 MEMBERS · 2 ACTIVE CHALLENGES")
    }

    @Test func decodesActivityFeed() throws {
        let entries = try decode([GroupActivityEntry].self, Self.activityJSON)

        #expect(entries.map(\.kind) == ["challenge_created", "member_joined"])
        #expect(entries[0].text == "started 30 DAY STEPS WAR")
    }

    @Test func encodesACreateRequestWithSnakeCaseKeys() throws {
        let request = CreateChallengeRequest(
            name: "PUSH WAR",
            activityType: .pushups,
            targetValue: "40",
            unit: "reps",
            gameMode: .points,
            verificationMethod: .manualProof,
            durationDays: 14,
            participantLimit: nil
        )

        let data = try #require(Endpoint.encodedBody(request))
        let json = try #require(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )

        #expect(json["activity_type"] as? String == "pushups")
        #expect(json["game_mode"] as? String == "points")
        #expect(json["verification_method"] as? String == "manual_proof")
        #expect(json["duration_days"] as? Int == 14)
        // No `status` field — the server decides DRAFT vs ACTIVE, never the client.
        #expect(json["status"] == nil)
    }

    // MARK: - Payloads captured from the local backend

    private static let groupDetailJSON = """
    {"id":"4d1f9e42-1b2c-4a3d-9e8f-0a1b2c3d4e5f","name":"KITS FITNESS WAR",
     "timezone":"Asia/Kolkata","privacy":"invite",
     "owner_id":"9a8b7c6d-5e4f-4a3b-8c9d-0e1f2a3b4c5d","member_count":1,
     "active_challenge_count":0,"created_at":"2026-09-02T06:46:53.300223Z",
     "join_code":"K7-XR9","my_role":"owner"}
    """

    private static let groupListJSON = """
    [{"id":"4d1f9e42-1b2c-4a3d-9e8f-0a1b2c3d4e5f","name":"KITS FITNESS WAR",
      "timezone":"Asia/Kolkata","member_count":3,"active_challenge_count":2}]
    """

    private static let challengeSummaryJSON = """
    {"id":"1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
     "group_id":"4d1f9e42-1b2c-4a3d-9e8f-0a1b2c3d4e5f","name":"30 DAY STEPS WAR",
     "activity_type":"steps","game_mode":"survival","status":"active",
     "target_value": "10000.00","unit":"steps","day_index":1,"duration_days":30,
     "participant_count":1,"my_status":"active"}
    """

    private static let challengeDetailJSON = """
    {"id":"1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
     "group_id":"4d1f9e42-1b2c-4a3d-9e8f-0a1b2c3d4e5f","group_name":"KITS FITNESS WAR",
     "creator_id":"9a8b7c6d-5e4f-4a3b-8c9d-0e1f2a3b4c5d","name":"30 DAY STEPS WAR",
     "activity_type":"steps","game_mode":"survival","verification_method":"apple_health",
     "status":"active","target_value":"10000.00","unit":"steps","timezone":"Asia/Kolkata",
     "start_at":"2026-09-02T06:44:46.145436Z","end_at":"2026-10-01T18:30:00Z",
     "day_index":1,"duration_days":30,"participant_count":1,"participant_limit":null,
     "failure_rule":"MISS TWICE → ELIMINATED","my_status":"active",
     "participants":[{"user_id":"9a8b7c6d-5e4f-4a3b-8c9d-0e1f2a3b4c5d",
       "display_name":"Ravi","status":"active","outcome":null,"current_score":"0.00",
       "current_streak":0,"rank":1,"joined_at":"2026-09-02T06:44:46.150000Z"}]}
    """

    private static let dailyProgressJSON = """
    {"challenge_day":"2026-09-02","day_index":1,"status":"pending",
     "target":"10000.00","unit":"steps",
     "window_start_at":"2026-09-01T18:30:00Z","deadline_at":"2026-09-02T18:30:00Z",
     "completed_at":null}
    """

    private static let activityJSON = """
    [{"kind":"challenge_created","actor_display_name":"Ravi",
      "text":"started 30 DAY STEPS WAR","occurred_at":"2026-09-02T06:44:46.145436Z"},
     {"kind":"member_joined","actor_display_name":"Sai","text":"joined the squad",
      "occurred_at":"2026-09-02T06:40:11.000000Z"}]
    """
}
