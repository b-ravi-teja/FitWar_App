import Foundation
import Observation

/// "CHALLENGE SOMEONE" — pick a squad, pick a rival, declare war.
///
/// The rival list and every head-to-head record come from the server. Which rivals are
/// already unavailable (a battle is running with them) is also the server's answer,
/// surfaced as `liveBattleId` rather than inferred from a list this screen holds.
@MainActor
@Observable
final class CreateBattleViewModel {
    private(set) var groupsState: LoadState<[GroupSummary]> = .loading
    private(set) var rivalsState: LoadState<[BattleRival]> = .loading
    private(set) var actionError: String?
    private(set) var isSubmitting = false
    private(set) var createdBattle: Battle?

    var selectedGroupId: UUID? {
        didSet { if oldValue != selectedGroupId { reloadRivalsTask() } }
    }

    var activity: ActivityType = .steps
    var durationDays: Int = 7
    /// Empty means "use the activity's default", which the server fills in — the client
    /// does not carry its own copy of the default to send.
    var targetText: String = ""

    private let battles: BattlesServiceProtocol
    private let groups: GroupsServiceProtocol
    private let sessionManager: SessionManager

    init(
        battles: BattlesServiceProtocol,
        groups: GroupsServiceProtocol,
        sessionManager: SessionManager
    ) {
        self.battles = battles
        self.groups = groups
        self.sessionManager = sessionManager
    }

    /// Activities a battle can measure. Push-ups are excluded because a battle verifies
    /// from health data and HealthKit has no push-up count — offering it would be a
    /// button the server rejects.
    static let selectableActivities: [ActivityType] = [.steps, .activeCalories, .distance]

    var rivals: [BattleRival] { rivalsState.value ?? [] }

    func load() async {
        groupsState = .loading
        do {
            let all = try await sessionManager.authorizedRequest { try await groups.listGroups() }
            groupsState = .loaded(all)
            if selectedGroupId == nil { selectedGroupId = all.first?.id }
            await loadRivals()
        } catch {
            groupsState = LoadState.from(error)
        }
    }

    func loadRivals() async {
        guard let groupId = selectedGroupId else {
            rivalsState = .loaded([])
            return
        }
        rivalsState = .loading
        do {
            rivalsState = .loaded(
                try await sessionManager.authorizedRequest {
                    try await battles.fetchRivals(groupId: groupId)
                }
            )
        } catch {
            rivalsState = LoadState.from(error)
        }
    }

    private func reloadRivalsTask() {
        Task { await loadRivals() }
    }

    func challenge(_ rival: BattleRival) async {
        guard !isSubmitting, let groupId = selectedGroupId else { return }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }
        let trimmed = targetText.trimmingCharacters(in: .whitespaces)
        do {
            createdBattle = try await sessionManager.authorizedRequest {
                try await battles.createBattle(
                    CreateBattleRequest(
                        opponentUserId: rival.userId,
                        activityType: activity,
                        targetValue: trimmed.isEmpty ? nil : trimmed,
                        durationDays: durationDays,
                        groupId: groupId
                    )
                )
            }
        } catch {
            actionError = BattleErrorPresentation.message(for: error)
        }
    }

    func clearCreatedBattle() {
        createdBattle = nil
    }
}
