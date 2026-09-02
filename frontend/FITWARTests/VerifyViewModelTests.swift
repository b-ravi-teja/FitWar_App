import Foundation
import Testing

@testable import FITWAR

@MainActor
struct VerifyViewModelTests {
    private func makeSUT(
        verificationMethod: VerificationMethod = .appleHealth
    ) -> (VerifyViewModel, MockChallengesService, MockVerificationService, MockHealthKitService) {
        let challenges = MockChallengesService()
        let verification = MockVerificationService()
        let health = MockHealthKitService()
        challenges.todayResult = .success(Fixture.dailyProgress())
        let sut = VerifyViewModel(
            challenge: Fixture.challengeDetail(verificationMethod: verificationMethod),
            challenges: challenges,
            verification: verification,
            health: health,
            media: MockMediaService()
        )
        return (sut, challenges, verification, health)
    }

    // MARK: - Authorization state mapping

    @Test func showsUnavailableWhenHealthKitIsMissing() async {
        let (sut, _, _, health) = makeSUT()
        health.available = false

        await sut.load()

        #expect(sut.state == .healthUnavailable)
    }

    @Test func showsConnectPromptWhenNeverAsked() async {
        let (sut, _, _, health) = makeSUT()
        health.authorization = .notDetermined

        await sut.load()

        #expect(sut.state == .notConnected)
    }

    @Test func readingNothingIsReportedAsAmbiguousRatherThanADenial() async {
        /// iOS never tells an app that read access was refused, so a zero reading must
        /// not be presented as a denial — it states both possibilities instead.
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "0.00"))
        verification.submitResult = .success(
            VerificationFixtures.response(
                dayStatus: .pending, status: .inconclusive, reasonCode: "TARGET_NOT_MET", value: 0
            )
        )

        await sut.load()
        await sut.sync()

        guard case .noActivityFound = sut.state else {
            Issue.record("expected noActivityFound, got \(sut.state)")
            return
        }
    }

    @Test func isReadyToSyncOnceAuthorizationWasRequested() async {
        let (sut, _, _, health) = makeSUT()
        health.authorization = .requested

        await sut.load()

        #expect(sut.state == .readyToSync(Fixture.dailyProgress()))
    }

    @Test func connectingRecordsTheLinkServerSide() async {
        let (sut, _, verification, health) = makeSUT()
        health.authorization = .notDetermined
        health.requestResult = .success(.requested)
        verification.connectResult = .success(
            HealthConnection(
                id: UUID(),
                provider: .appleHealth,
                status: .connected,
                lastSyncedAt: nil,
                connectedAt: Date()
            )
        )

        await sut.connectHealth()

        #expect(verification.connectCallCount == 1)
        #expect(health.requestedActivities == [.steps])
    }

    @Test func aFailedConnectionRecordDoesNotBlockVerification() async {
        /// The link row is a convenience; losing it must not stop a user verifying.
        let (sut, _, verification, health) = makeSUT()
        health.authorization = .notDetermined
        health.requestResult = .success(.requested)
        verification.connectResult = .failure(APIError.noConnection)

        await sut.connectHealth()

        // `load()` ran afterwards and reached a usable state.
        #expect(sut.state == .readyToSync(Fixture.dailyProgress()))
    }

    // MARK: - The timezone rule

    @Test func readsHealthDataOverTheServersWindowNotTheDeviceDay() async {
        /// The critical correctness property: the challenge day belongs to the
        /// challenge's frozen timezone, which is frequently not the device's.
        let (sut, _, verification, health) = makeSUT()
        let progress = Fixture.dailyProgress()
        health.evidenceResult = .success(VerificationFixtures.evidence())
        verification.submitResult = .success(VerificationFixtures.response())

        await sut.load()
        await sut.sync()

        #expect(health.readWindows.count == 1)
        #expect(health.readWindows[0].start == progress.windowStartAt)
        // The read never runs past the deadline the server published.
        #expect(health.readWindows[0].end <= progress.deadlineAt)
    }

    @Test func readsOnlyTheMetricTheChallengeMeasures() async {
        /// No broad health reads — only what this challenge needs.
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence())
        verification.submitResult = .success(VerificationFixtures.response())

        await sut.load()
        await sut.sync()

        #expect(health.readActivities == [.steps])
    }

    // MARK: - Server-authoritative outcomes

    @Test func completionComesFromTheServerNotTheClient() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "12000"))
        verification.submitResult = .success(VerificationFixtures.response(dayStatus: .completed))

        await sut.load()
        await sut.sync()

        guard case .verified = sut.state else {
            Issue.record("expected verified, got \(sut.state)")
            return
        }
    }

    @Test func aHugeLocalValueStillLosesToTheServersVerdict() async {
        /// Even with a big number in hand, the client renders what the server decided.
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "999999"))
        verification.submitResult = .success(
            VerificationFixtures.response(
                dayStatus: .pending, status: .inconclusive, reasonCode: "USER_ENTERED_DATA"
            )
        )

        await sut.load()
        await sut.sync()

        guard case .insufficient = sut.state else {
            Issue.record("expected insufficient, got \(sut.state)")
            return
        }
    }

    @Test func shortOfTargetLeavesTheDayOpen() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "4000"))
        verification.submitResult = .success(
            VerificationFixtures.response(
                dayStatus: .pending, status: .inconclusive, reasonCode: "TARGET_NOT_MET", value: 4000
            )
        )

        await sut.load()
        await sut.sync()

        guard case .insufficient(_, let record) = sut.state else {
            Issue.record("expected insufficient, got \(sut.state)")
            return
        }
        #expect(record.reasonCode == "TARGET_NOT_MET")
    }

    @Test func anIdempotentReplayIsShownAsAlreadyComplete() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence())
        verification.submitResult = .success(VerificationFixtures.response(idempotentReplay: true))

        await sut.load()
        await sut.sync()

        guard case .verified(let response) = sut.state else {
            Issue.record("expected verified, got \(sut.state)")
            return
        }
        #expect(response.idempotentReplay)
    }

    // MARK: - Request payload

    @Test func submitsNormalizedEvidenceWithExplicitUnits() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(value: "12000"))
        verification.submitResult = .success(VerificationFixtures.response())

        await sut.load()
        await sut.sync()

        #expect(verification.submittedRequests.count == 1)
        let request = verification.submittedRequests[0]
        #expect(request.provider == .appleHealth)
        #expect(request.evidence.unit == "steps")
        #expect(request.evidence.value == "12000")
        #expect(request.evidence.wasUserEntered == false)
    }

    @Test func reportsHandEnteredDataRatherThanHidingIt() async {
        /// The client states the fact; the server decides what it's worth.
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence(wasUserEntered: true))
        verification.submitResult = .success(
            VerificationFixtures.response(
                dayStatus: .pending, status: .inconclusive, reasonCode: "USER_ENTERED_DATA"
            )
        )

        await sut.load()
        await sut.sync()

        #expect(verification.submittedRequests[0].evidence.wasUserEntered)
    }

    // MARK: - Error mapping

    @Test func networkFailureIsDistinctFromServerError() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence())
        verification.submitResult = .failure(APIError.noConnection)

        await sut.load()
        await sut.sync()

        #expect(sut.state == .networkFailure)
    }

    @Test func invalidEvidenceIsShownAsRejection() async {
        let (sut, _, verification, health) = makeSUT()
        health.evidenceResult = .success(VerificationFixtures.evidence())
        verification.submitResult = .failure(
            APIError.server(status: 400, code: "INVALID_EVIDENCE", detail: "Wrong unit.")
        )

        await sut.load()
        await sut.sync()

        #expect(sut.state == .rejected("Wrong unit."))
    }

    @Test func healthKitFailureNeverLeaksFrameworkText() async {
        /// Users see product copy, never an NSError description.
        let (sut, _, _, health) = makeSUT()
        health.evidenceResult = .failure(HealthKitError.queryFailed)

        await sut.load()
        await sut.sync()

        guard case .rejected(let message) = sut.state else {
            Issue.record("expected rejected, got \(sut.state)")
            return
        }
        #expect(!message.lowercased().contains("healthkit"))
        #expect(!message.lowercased().contains("nserror"))
    }

    @Test func anUnsupportedMetricIsAProductError() async {
        let (sut, _, _, health) = makeSUT()
        health.evidenceResult = .failure(HealthKitError.unsupportedMetric(.pushups))

        await sut.load()
        await sut.sync()

        guard case .rejected = sut.state else {
            Issue.record("expected rejected, got \(sut.state)")
            return
        }
    }
}

@MainActor
struct VerificationReasonPresentationTests {
    @Test func explainsHowFarShortTheUserIs() {
        let record = VerificationFixtures.record(
            status: .inconclusive, value: 4000, target: 10_000, reasonCode: "TARGET_NOT_MET"
        )

        let message = VerificationReasonPresentation.message(for: record, unit: "steps")

        #expect(message.contains("6,000") || message.contains("6000"))
    }

    @Test func explainsWhyHandEnteredDataIsNotCounted() {
        let record = VerificationFixtures.record(
            status: .inconclusive, reasonCode: "USER_ENTERED_DATA"
        )

        let message = VerificationReasonPresentation.message(for: record, unit: "steps")

        #expect(message.lowercased().contains("hand"))
    }

    @Test func fallsBackWithoutInventingADiagnosis() {
        let record = VerificationFixtures.record(status: .rejected, reasonCode: "SOMETHING_NEW")

        let message = VerificationReasonPresentation.message(for: record, unit: "steps")

        #expect(!message.isEmpty)
    }
}
