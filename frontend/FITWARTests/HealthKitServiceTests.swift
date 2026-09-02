import Foundation
import HealthKit
import Testing

@testable import FITWAR

/// Tests for the parts of the HealthKit boundary that are decidable without a live
/// Health database.
///
/// What is deliberately NOT tested here: actual sample reads and the authorization
/// sheet. Both need `HKHealthStore` backed by real Health data and a user tapping a
/// system prompt, which no headless unit test can provide. Those paths are exercised
/// through `HealthKitServicing` fakes in `VerifyViewModelTests`, and the limitation is
/// recorded in docs/ARCHITECTURE.md rather than papered over with a test that asserts
/// nothing real.
struct HealthKitServiceTests {
    @Test func formatsValuesToThePrecisionTheServerStores() {
        /// The backend column is Numeric(12,2); sending more precision would be
        /// silently truncated, and sending a float literal risks 0.30000000000000004.
        #expect(HealthKitService.format(12_000) == "12000.00")
        #expect(HealthKitService.format(5.126) == "5.13")
        #expect(HealthKitService.format(0) == "0.00")
    }

    @Test func reportsAvailabilityFromTheSystem() {
        /// Not asserting a fixed value: availability legitimately differs between a
        /// simulator, an iPad, and a phone, and hard-coding either answer would make
        /// this test a lie on some machine.
        let service = HealthKitService()
        #expect(service.isAvailable == HKHealthStore.isHealthDataAvailable())
    }

    @Test func pushupsAreNotReadableFromHealthData() async {
        /// HealthKit cannot count push-ups, so such a challenge must fail loudly as a
        /// configuration error rather than silently reading zero and marking a miss.
        let service = HealthKitService()
        guard service.isAvailable else { return }

        await #expect(throws: HealthKitError.self) {
            _ = try await service.readEvidence(
                for: .pushups, start: Date(timeIntervalSince1970: 0), end: Date()
            )
        }
    }
}

struct HealthAuthorizationStateTests {
    @Test func requestedIsDistinctFromAuthorized() {
        /// The naming matters: iOS never tells us a read request was *granted*, only
        /// that the sheet completed. A case called `.authorized` would be a claim the
        /// platform doesn't support.
        let states: [HealthAuthorizationState] = [.unavailable, .notDetermined, .requested]
        let names = states.map(String.init(describing:))
        #expect(Set(names).count == 3)
        // Neither `authorized` nor `denied` exists: for a read-only request iOS reports
        // neither, and a case named for an outcome we cannot observe would be a lie.
        #expect(!names.contains("authorized"))
        #expect(!names.contains("denied"))
    }
}
