import Foundation
@testable import FITWAR

/// Stand-in for the HealthKit boundary.
///
/// Unit tests never touch `HKHealthStore`: it needs entitlements, a real Health
/// database, and user interaction, none of which belong in a test that must run
/// headlessly. Faking at the protocol is exactly what the boundary exists for.
final class MockHealthKitService: HealthKitServicing, @unchecked Sendable {
    var available = true
    var authorization: HealthAuthorizationState = .requested
    var requestResult: Result<HealthAuthorizationState, Error> = .success(.requested)
    var evidenceResult: Result<HealthEvidencePayload, Error> = .failure(
        HealthKitError.queryFailed
    )

    private(set) var requestedActivities: [ActivityType] = []
    private(set) var readWindows: [(start: Date, end: Date)] = []
    private(set) var readActivities: [ActivityType] = []

    var isAvailable: Bool { available }

    func authorizationState(for activity: ActivityType) async -> HealthAuthorizationState {
        available ? authorization : .unavailable
    }

    func requestAuthorization(for activity: ActivityType) async throws -> HealthAuthorizationState {
        requestedActivities.append(activity)
        let result = try requestResult.get()
        // Mirrors the real service: once the sheet completes, the state HealthKit
        // reports back changes. A mock that stayed on `.notDetermined` would make the
        // post-request reload look broken when it isn't.
        authorization = result
        return result
    }

    func readEvidence(
        for activity: ActivityType, start: Date, end: Date
    ) async throws -> HealthEvidencePayload {
        readActivities.append(activity)
        readWindows.append((start, end))
        return try evidenceResult.get()
    }
}

final class MockVerificationService: VerificationServiceProtocol, @unchecked Sendable {
    var submitResult: Result<SubmitVerificationResponse, Error> = .failure(
        APIError.unknown("not configured")
    )
    var connectionsResult: Result<[HealthConnection], Error> = .success([])
    var connectResult: Result<HealthConnection, Error> = .failure(
        APIError.unknown("not configured")
    )
    var disconnectError: Error?

    private(set) var submittedRequests: [SubmitVerificationRequest] = []
    private(set) var connectCallCount = 0

    func submitVerification(
        challengeId: UUID, request: SubmitVerificationRequest
    ) async throws -> SubmitVerificationResponse {
        submittedRequests.append(request)
        return try submitResult.get()
    }

    func listHealthConnections() async throws -> [HealthConnection] {
        try connectionsResult.get()
    }

    func connectHealthProvider(_ provider: HealthProviderKindDTO) async throws -> HealthConnection {
        connectCallCount += 1
        return try connectResult.get()
    }

    func disconnectHealthProvider(id: UUID) async throws {
        if let disconnectError { throw disconnectError }
    }
}

enum VerificationFixtures {
    static func evidence(
        value: String = "12000",
        metric: ActivityType = .steps,
        unit: String = "steps",
        wasUserEntered: Bool = false
    ) -> HealthEvidencePayload {
        HealthEvidencePayload(
            metric: metric,
            value: value,
            unit: unit,
            periodStart: Date(timeIntervalSince1970: 1_760_000_000),
            periodEnd: Date(timeIntervalSince1970: 1_760_050_000),
            sourceName: "iPhone",
            sourceBundleId: "com.fitwar.app",
            wasUserEntered: wasUserEntered
        )
    }

    static func record(
        status: VerificationStatus = .verified,
        value: Decimal = 12_000,
        target: Decimal = 10_000,
        reasonCode: String? = nil
    ) -> VerificationRecord {
        VerificationRecord(
            id: UUID(),
            provider: "apple_health",
            metric: "steps",
            value: value,
            target: target,
            status: status,
            reasonCode: reasonCode,
            sourceTimestamp: Date(timeIntervalSince1970: 1_760_050_000),
            verifiedAt: status == .verified ? Date(timeIntervalSince1970: 1_760_050_500) : nil
        )
    }

    static func response(
        dayStatus: DailyProgressStatus = .completed,
        status: VerificationStatus = .verified,
        reasonCode: String? = nil,
        value: Decimal = 12_000,
        idempotentReplay: Bool = false
    ) -> SubmitVerificationResponse {
        SubmitVerificationResponse(
            verification: record(status: status, value: value, reasonCode: reasonCode),
            challengeDay: Date(timeIntervalSince1970: 1_760_000_000),
            dayStatus: dayStatus,
            deadlineAt: Date(timeIntervalSince1970: 1_760_086_400),
            idempotentReplay: idempotentReplay
        )
    }
}
