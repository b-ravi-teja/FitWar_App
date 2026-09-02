import Foundation
import Observation

/// The design's 5-step create flow: activity → mode → rules → invite → review.
///
/// Holds only configuration. It never sends a status — the server decides whether the
/// new challenge is DRAFT or ACTIVE (Architecture §1 tenet 1).
@MainActor
@Observable
final class CreateChallengeViewModel {
    enum Step: Int, CaseIterable {
        case activity, mode, rules, invite, review

        var ctaTitle: String { self == .review ? "START CHALLENGE" : "CONTINUE" }
    }

    private(set) var step: Step = .activity
    private(set) var isSubmitting = false
    private(set) var errorMessage: String?

    let group: GroupSummary
    var joinCode: String = ""

    var activity: ActivityType = .steps
    var mode: GameMode = .survival
    var verification: VerificationMethod = .appleHealth
    var durationDays: Int = 30
    var targetValue: Int = ActivityType.steps.defaultTarget
    var name: String = ""

    private let challengesService: ChallengesServiceProtocol
    private let groupsService: GroupsServiceProtocol
    private let sessionManager: SessionManager

    init(
        group: GroupSummary,
        challengesService: ChallengesServiceProtocol,
        groupsService: GroupsServiceProtocol,
        sessionManager: SessionManager
    ) {
        self.group = group
        self.challengesService = challengesService
        self.groupsService = groupsService
        self.sessionManager = sessionManager
    }

    // MARK: Navigation

    var isFirstStep: Bool { step == .activity }

    func advance() {
        guard let next = Step(rawValue: step.rawValue + 1) else { return }
        step = next
    }

    func goBack() {
        guard let previous = Step(rawValue: step.rawValue - 1) else { return }
        step = previous
    }

    // MARK: Configuration

    func select(activity: ActivityType) {
        self.activity = activity
        // The unit and a sensible target follow from the activity, so switching from
        // Steps to Push-ups doesn't leave a 10,000-rep daily target behind.
        targetValue = activity.defaultTarget
        if name.isEmpty || name == Self.suggestedName(for: self.activity, days: durationDays) {
            name = Self.suggestedName(for: activity, days: durationDays)
        }
    }

    static func suggestedName(for activity: ActivityType, days: Int) -> String {
        "\(days) DAY \(activity.displayName.uppercased()) WAR"
    }

    var resolvedName: String {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? Self.suggestedName(for: activity, days: durationDays) : trimmed
    }

    var targetLabel: String { "\(FWNumber.compact(targetValue)) \(activity.unit.uppercased())" }
    var durationLabel: String { "\(durationDays) DAYS" }

    var failureRuleLabel: String {
        mode == .survival ? "2 MISSES → OUT" : "NO ELIMINATION"
    }

    /// The rules the design's step-3 list shows, built from real configuration.
    /// "Progression" and "Rest days" from the prototype's mock list are omitted —
    /// neither is a V1 rule, and listing them would imply configuration that doesn't exist.
    var ruleRows: [(label: String, value: String)] {
        [
            ("Duration", durationLabel),
            ("Daily target", targetLabel),
            ("Game mode", mode.displayName),
            ("Verification", verification.displayName),
        ]
    }

    // MARK: Invite step

    /// The squad's existing join code — the invite step shares the group people are
    /// already in, rather than minting a per-challenge code that nothing would honour.
    func loadJoinCode() async {
        guard joinCode.isEmpty else { return }
        if let detail = try? await sessionManager.authorizedRequest({
            try await self.groupsService.fetchGroup(id: self.group.id)
        }) {
            joinCode = detail.joinCode
        }
    }

    // MARK: Submission

    func submit() async -> ChallengeDetail? {
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }

        let request = CreateChallengeRequest(
            name: resolvedName,
            activityType: activity,
            targetValue: String(targetValue),
            unit: activity.unit,
            gameMode: mode,
            verificationMethod: verification,
            durationDays: durationDays,
            participantLimit: nil
        )

        do {
            return try await sessionManager.authorizedRequest {
                try await self.challengesService.createChallenge(
                    groupId: self.group.id, request: request
                )
            }
        } catch {
            errorMessage = DomainErrorPresentation.message(for: error)
            return nil
        }
    }
}
