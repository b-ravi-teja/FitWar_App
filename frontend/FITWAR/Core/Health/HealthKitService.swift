import Foundation
import HealthKit

/// The HealthKit boundary. Everything Apple-specific stops here.
///
/// Above this file the app deals in `HealthEvidencePayload` — plain numbers, units and
/// UTC instants — which is the same shape the backend's `VerificationProvider`
/// abstraction consumes (Architecture §8). SwiftUI views never import HealthKit, never
/// see an `HKQuantitySample`, and never decide whether a challenge was completed.
///
/// A known limitation, stated plainly because pretending otherwise produces a lying UI:
/// **iOS does not report read-permission outcomes.** `authorizationStatus(for:)` describes
/// *share* (write) access only — for a read-only request it returns `.sharingDenied`
/// whether or not the user granted reading, so branching on it would tell a user who just
/// tapped Allow that access is off. Apple hides read denials deliberately, so apps cannot
/// detect them.
///
/// `statusForAuthorizationRequest` is therefore the only sound signal: it says whether the
/// system *would* prompt, which distinguishes "never asked" from "already asked" without
/// claiming to know the answer. `.requested` encodes exactly that uncertainty, and the UI
/// resolves it by reporting what was actually read plus a Settings path — never by
/// asserting a denial it cannot observe.
protocol HealthKitServicing: Sendable {
    var isAvailable: Bool { get }
    func authorizationState(for activity: ActivityType) async -> HealthAuthorizationState
    func requestAuthorization(for activity: ActivityType) async throws -> HealthAuthorizationState
    /// Reads one aggregate for exactly `[start, end)`. The window comes from the server,
    /// never from the device calendar — see `VerifyViewModel`.
    func readEvidence(
        for activity: ActivityType, start: Date, end: Date
    ) async throws -> HealthEvidencePayload
}

enum HealthAuthorizationState: Sendable, Equatable {
    /// HealthKit isn't on this device at all (iPad without Health, some simulators).
    case unavailable
    /// The system would prompt — the user has never been asked.
    case notDetermined
    /// The system would not prompt: the user has been asked. Whether they granted read
    /// access is deliberately unknowable (see the note above), so there is no
    /// `.authorized` or `.denied` case for reads — inventing one would be a claim the
    /// platform does not support.
    case requested
}

enum HealthKitError: Error, Equatable {
    case unavailable
    case unsupportedMetric(ActivityType)
    case authorizationFailed
    /// HealthKit refused the read. This is as close as iOS comes to admitting a read
    /// denial — it never says so directly, but a query that fails on authorization
    /// rather than returning an empty result is the strongest signal available.
    case notAuthorized
    case queryFailed
}

private func mapQueryError(_ error: Error) -> HealthKitError {
    let code = (error as NSError).code
    if (error as NSError).domain == HKError.errorDomain,
       code == HKError.errorAuthorizationDenied.rawValue
        || code == HKError.errorAuthorizationNotDetermined.rawValue
    {
        return .notAuthorized
    }
    return .queryFailed
}

struct HealthKitService: HealthKitServicing {
    private let store: HKHealthStore

    init(store: HKHealthStore = HKHealthStore()) {
        self.store = store
    }

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func authorizationState(for activity: ActivityType) async -> HealthAuthorizationState {
        guard isAvailable else { return .unavailable }
        guard let type = Self.quantityType(for: activity) else { return .unavailable }
        do {
            let status = try await store.statusForAuthorizationRequest(toShare: [], read: [type])
            switch status {
            case .shouldRequest: return .notDetermined
            case .unnecessary: return .requested
            // `.unknown` means HealthKit couldn't determine it; asking again is safe and
            // is better than guessing the user was already prompted.
            case .unknown: return .notDetermined
            @unknown default: return .notDetermined
            }
        } catch {
            return .notDetermined
        }
    }

    func requestAuthorization(for activity: ActivityType) async throws -> HealthAuthorizationState {
        guard isAvailable else { throw HealthKitError.unavailable }
        guard let type = Self.quantityType(for: activity) else {
            throw HealthKitError.unsupportedMetric(activity)
        }
        do {
            // Read-only: FITWAR never writes to Health. The empty share set is what
            // makes the onboarding copy ("Everything else — NEVER") literally true.
            try await store.requestAuthorization(toShare: [], read: [type])
        } catch {
            throw HealthKitError.authorizationFailed
        }
        // Completing the sheet tells us the user was asked, not what they chose.
        return .requested
    }

    func readEvidence(
        for activity: ActivityType, start: Date, end: Date
    ) async throws -> HealthEvidencePayload {
        guard isAvailable else { throw HealthKitError.unavailable }
        guard
            let type = Self.quantityType(for: activity),
            let unit = Self.unit(for: activity)
        else {
            throw HealthKitError.unsupportedMetric(activity)
        }

        // Strict bounds: a sample must start and end inside the window to count, so a
        // walk spanning midnight can't be credited to both days.
        let window = HKQuery.predicateForSamples(
            withStart: start, end: end, options: [.strictStartDate, .strictEndDate]
        )

        let total = try await sum(type: type, unit: unit, predicate: window)
        let userEntered = try await containsUserEnteredSample(type: type, predicate: window)

        return HealthEvidencePayload(
            metric: activity,
            value: Self.format(total),
            unit: activity.unit,
            periodStart: start,
            periodEnd: end,
            sourceName: Self.deviceName,
            sourceBundleId: Bundle.main.bundleIdentifier,
            // Reported, not filtered out: the server decides what hand-entered data is
            // worth (Architecture §1 — the client submits facts, never verdicts).
            wasUserEntered: userEntered
        )
    }

    // MARK: - HealthKit plumbing

    private func sum(type: HKQuantityType, unit: HKUnit, predicate: NSPredicate) async throws -> Double {
        try await withCheckedThrowingContinuation { continuation in
            let query = HKStatisticsQuery(
                quantityType: type,
                quantitySamplePredicate: predicate,
                options: .cumulativeSum
            ) { _, statistics, error in
                if let error {
                    continuation.resume(throwing: mapQueryError(error))
                    return
                }
                // No samples is not an error — it is a real answer meaning "nothing
                // recorded in this window", which the server scores as short of target.
                let value = statistics?.sumQuantity()?.doubleValue(for: unit) ?? 0
                continuation.resume(returning: value)
            }
            store.execute(query)
        }
    }

    private func containsUserEnteredSample(
        type: HKQuantityType, predicate: NSPredicate
    ) async throws -> Bool {
        let userEntered = HKQuery.predicateForObjects(
            withMetadataKey: HKMetadataKeyWasUserEntered, allowedValues: [true]
        )
        let combined = NSCompoundPredicate(andPredicateWithSubpredicates: [predicate, userEntered])

        return try await withCheckedThrowingContinuation { continuation in
            // One result is enough — this asks "was any of this typed in?", not "how much".
            let query = HKSampleQuery(
                sampleType: type, predicate: combined, limit: 1, sortDescriptors: nil
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: mapQueryError(error))
                    return
                }
                continuation.resume(returning: !(samples ?? []).isEmpty)
            }
            store.execute(query)
        }
    }

    private static func quantityType(for activity: ActivityType) -> HKQuantityType? {
        switch activity {
        case .steps: HKQuantityType(.stepCount)
        case .activeCalories: HKQuantityType(.activeEnergyBurned)
        case .distance: HKQuantityType(.distanceWalkingRunning)
        // HealthKit cannot count push-ups; such a challenge is manual-proof only, and
        // returning nil is what surfaces that as a clear product error rather than a
        // silent zero.
        case .pushups: nil
        }
    }

    private static func unit(for activity: ActivityType) -> HKUnit? {
        switch activity {
        case .steps: .count()
        case .activeCalories: .kilocalorie()
        // Read straight in kilometres, the unit the challenge target uses — no
        // client-side conversion means no client-side conversion bug.
        case .distance: .meterUnit(with: .kilo)
        case .pushups: nil
        }
    }

    /// Two decimal places, matching the backend's `Numeric(12, 2)` so a value never
    /// fails validation for precision the server can't store.
    static func format(_ value: Double) -> String {
        String(format: "%.2f", value)
    }

    private static var deviceName: String {
        #if canImport(UIKit)
            return UIDevice.current.model
        #else
            return "iPhone"
        #endif
    }
}

#if canImport(UIKit)
    import UIKit
#endif
