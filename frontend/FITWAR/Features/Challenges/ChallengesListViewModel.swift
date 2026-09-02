import Foundation
import Observation

/// Backs the WARS tab. ACTIVE and COMPLETED only — the prototype's DISCOVER tab is
/// dropped from V1 (ADR 0001, no public challenge discovery).
@MainActor
@Observable
final class ChallengesListViewModel {
    enum Tab: String, CaseIterable {
        case active = "ACTIVE"
        case completed = "COMPLETED"

        var status: ChallengeStatus {
            switch self {
            case .active: .active
            case .completed: .completed
            }
        }
    }

    private(set) var state: LoadState<[ChallengeSummary]> = .loading
    /// Groups the user belongs to — the create flow needs one to create a challenge in,
    /// and with none the right answer is "make a squad first", not an empty picker.
    private(set) var groups: [GroupSummary] = []

    var selectedTab: Tab = .active {
        didSet {
            guard oldValue != selectedTab else { return }
            Task { await load() }
        }
    }

    private let challengesService: ChallengesServiceProtocol
    private let groupsService: GroupsServiceProtocol
    private let sessionManager: SessionManager

    init(
        challengesService: ChallengesServiceProtocol,
        groupsService: GroupsServiceProtocol,
        sessionManager: SessionManager
    ) {
        self.challengesService = challengesService
        self.groupsService = groupsService
        self.sessionManager = sessionManager
    }

    var challenges: [ChallengeSummary] { state.value ?? [] }
    var canCreate: Bool { !groups.isEmpty }

    func load() async {
        state = .loading
        await reload()
    }

    func reload() async {
        do {
            let result = try await sessionManager.authorizedRequest {
                async let challenges = self.challengesService.listMyChallenges(
                    status: self.selectedTab.status
                )
                async let groups = self.groupsService.listGroups()
                return (try await challenges, try await groups)
            }
            groups = result.1
            state = .loaded(result.0)
        } catch {
            state = .from(error)
        }
    }

    func acknowledgeUnauthorized() {
        sessionManager.acknowledgeSessionExpired()
    }
}
