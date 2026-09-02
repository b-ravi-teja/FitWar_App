import Foundation
import Observation

/// Every state the Verify screen can be in. One enum rather than a set of booleans, so
/// impossible combinations ("fetching" while "denied") can't be represented.
enum VerifyState: Sendable, Equatable {
    case loadingDay
    case healthUnavailable
    case notConnected
    case requestingPermission
    /// Read nothing at all. iOS won't say whether that's a denial or genuinely no
    /// activity, so the UI states both possibilities instead of picking one.
    case noActivityFound(DailyProgress)
    case readyToSync(DailyProgress)
    case fetchingEvidence(DailyProgress)
    case submitting(DailyProgress)
    /// Server said the day is done.
    case verified(SubmitVerificationResponse)
    /// Evidence arrived but fell short, or couldn't be trusted. Not a failure — the day
    /// stays open until its deadline.
    case insufficient(DailyProgress, VerificationRecord)
    /// Server refused the evidence outright.
    case rejected(String)
    case networkFailure
    case serverError(String)
}

@MainActor
@Observable
final class VerifyViewModel {
    private(set) var state: VerifyState = .loadingDay

    private let challenge: ChallengeDetail
    private let challenges: ChallengesServiceProtocol
    private let verification: VerificationServiceProtocol
    private let health: HealthKitServicing

    init(
        challenge: ChallengeDetail,
        challenges: ChallengesServiceProtocol,
        verification: VerificationServiceProtocol,
        health: HealthKitServicing
    ) {
        self.challenge = challenge
        self.challenges = challenges
        self.verification = verification
        self.health = health
    }

    var challengeName: String { challenge.name }
    var activity: ActivityType { challenge.activityType }

    /// The day being verified, when one has been loaded.
    var day: DailyProgress? {
        switch state {
        case .readyToSync(let day), .fetchingEvidence(let day), .submitting(let day),
             .insufficient(let day, _):
            day
        default: nil
        }
    }

    func load() async {
        guard health.isAvailable else {
            state = .healthUnavailable
            return
        }
        state = .loadingDay
        do {
            let progress = try await challenges.fetchTodayProgress(challengeId: challenge.id)
            switch await health.authorizationState(for: challenge.activityType) {
            case .unavailable:
                state = .healthUnavailable
            case .notDetermined:
                state = .notConnected
            case .requested:
                state = .readyToSync(progress)
            }
        } catch {
            state = Self.failure(from: error)
        }
    }

    /// Connect Apple Health, then record the link server-side.
    func connectHealth() async {
        state = .requestingPermission
        do {
            let result = try await health.requestAuthorization(for: challenge.activityType)
            guard result == .requested else {
                state = .healthUnavailable
                return
            }
            // Best-effort: the link record is a convenience for Settings and the
            // last-synced signal, so a failure here must not block verification.
            _ = try? await verification.connectHealthProvider(.appleHealth)
            await load()
        } catch HealthKitError.unavailable, HealthKitError.unsupportedMetric {
            state = .healthUnavailable
        } catch {
            // The authorization call itself failed. That is not a denial — iOS doesn't
            // report those — so it's surfaced as a retryable problem.
            state = .rejected("Couldn't open Apple Health access. Try again.")
        }
    }

    /// Read today's evidence and submit it. The server decides the outcome.
    func sync() async {
        guard let day = day ?? state.dayForSync else { return }
        state = .fetchingEvidence(day)

        let payload: HealthEvidencePayload
        do {
            // The window is the server's, verbatim — never a device-local calendar day.
            payload = try await health.readEvidence(
                for: challenge.activityType,
                start: day.windowStartAt,
                end: min(day.deadlineAt, Date())
            )
        } catch HealthKitError.unavailable {
            state = .healthUnavailable
            return
        } catch HealthKitError.unsupportedMetric {
            state = .rejected("This challenge can't be measured from health data.")
            return
        } catch HealthKitError.notAuthorized {
            // HealthKit refused the read. iOS still won't confirm a denial outright, so
            // this lands in the same both-possibilities state with a Settings path.
            state = .noActivityFound(day)
            return
        } catch {
            // A HealthKit failure is shown as a product-level problem; the framework's
            // own error text is never surfaced to the user.
            state = .rejected("Couldn't read your health data. Try again.")
            return
        }

        // Zero is ambiguous on iOS: either nothing was recorded, or read access was
        // refused and HealthKit is returning an empty set. It still goes to the server
        // (which owns the verdict), but the UI says both rather than guessing.
        let readNothing = Decimal(string: payload.value) == 0

        state = .submitting(day)
        do {
            let response = try await verification.submitVerification(
                challengeId: challenge.id,
                request: SubmitVerificationRequest(provider: .appleHealth, evidence: payload)
            )
            if response.dayStatus == .completed {
                state = .verified(response)
            } else {
                state = readNothing ? .noActivityFound(day) : .insufficient(day, response.verification)
            }
        } catch {
            state = Self.failure(from: error)
        }
    }

    private static func failure(from error: Error) -> VerifyState {
        guard let apiError = error as? APIError else {
            return .serverError("Something went wrong. Try again.")
        }
        switch apiError {
        case .noConnection, .timeout:
            return .networkFailure
        case .server(let status, let code, _) where status == 400 && code == "INVALID_EVIDENCE":
            return .rejected(VerificationErrorPresentation.message(for: apiError))
        case .server:
            return .serverError(VerificationErrorPresentation.message(for: apiError))
        case .decodingFailed, .unknown:
            return .serverError("Something went wrong. Try again.")
        }
    }
}

private extension VerifyState {
    /// The day is still available in the states a retry can start from.
    var dayForSync: DailyProgress? {
        if case .insufficient(let day, _) = self { return day }
        return nil
    }
}

/// Backend `code` → user-facing copy for verification. Mirrors the Groups/Challenges
/// table in `LoadState.swift`: `code` is the stable contract, `detail` is not.
enum VerificationErrorPresentation {
    static func message(for error: Error) -> String {
        guard let apiError = error as? APIError,
              case .server(_, let code, let detail) = apiError
        else {
            return "Something went wrong. Try again."
        }
        switch code {
        case "INVALID_EVIDENCE":
            return detail
        case "VERIFICATION_METHOD_MISMATCH":
            return "This challenge doesn't use Apple Health."
        case "CHALLENGE_NOT_ACTIVE":
            return "This challenge isn't running right now."
        case "NOT_A_PARTICIPANT":
            return "You haven't joined this challenge."
        default:
            return detail
        }
    }
}

/// Human-readable explanation for a non-verified result. Keyed on `reason_code`, which
/// is the stable field — never on server prose.
enum VerificationReasonPresentation {
    static func message(for record: VerificationRecord, unit: String) -> String {
        switch record.reasonCode {
        case "TARGET_NOT_MET":
            let remaining = max(record.target - record.value, 0)
            return "\(FWNumber.compact(remaining)) \(unit) to go."
        case "USER_ENTERED_DATA":
            return "That data was entered by hand, so it can't be verified. "
                + "Recorded activity from your device or watch counts."
        default:
            return "That activity couldn't be verified yet."
        }
    }
}
