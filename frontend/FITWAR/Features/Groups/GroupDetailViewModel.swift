import Foundation
import Observation

/// Backs the Group screen. ROSTER and FEED are real; CHAT is deliberately not a tab
/// here — realtime chat is a later phase, and showing an empty tab labelled CHAT would
/// promise something that isn't built.
@MainActor
@Observable
final class GroupDetailViewModel {
    struct Content: Equatable {
        var group: GroupDetail
        var members: [GroupMemberSummary]
        var challenges: [ChallengeSummary]
        var activity: [GroupActivityEntry]
    }

    enum Tab: String, CaseIterable {
        case roster = "ROSTER"
        case feed = "FEED"
    }

    private(set) var state: LoadState<Content> = .loading
    var selectedTab: Tab = .roster
    private(set) var actionError: String?
    private(set) var isLeaving = false

    let groupId: UUID
    private let groupsService: GroupsServiceProtocol
    private let challengesService: ChallengesServiceProtocol
    private let sessionManager: SessionManager
    private let currentUserId: UUID?

    init(
        groupId: UUID,
        groupsService: GroupsServiceProtocol,
        challengesService: ChallengesServiceProtocol,
        sessionManager: SessionManager,
        currentUserId: UUID?
    ) {
        self.groupId = groupId
        self.groupsService = groupsService
        self.challengesService = challengesService
        self.sessionManager = sessionManager
        self.currentUserId = currentUserId
    }

    func isMe(_ userId: UUID) -> Bool { userId == currentUserId }

    func load() async {
        state = .loading
        await reload()
    }

    func reload() async {
        do {
            let content: Content = try await sessionManager.authorizedRequest {
                // Four independent reads; running them concurrently keeps the screen's
                // time-to-content at the slowest single call, not their sum.
                async let group = self.groupsService.fetchGroup(id: self.groupId)
                async let members = self.groupsService.fetchMembers(groupId: self.groupId)
                async let challenges = self.challengesService.listGroupChallenges(
                    groupId: self.groupId
                )
                async let activity = self.groupsService.fetchActivity(groupId: self.groupId)
                return Content(
                    group: try await group,
                    members: try await members,
                    challenges: try await challenges,
                    activity: try await activity
                )
            }
            state = .loaded(content)
        } catch {
            state = .from(error)
        }
    }

    func leaveGroup() async -> Bool {
        isLeaving = true
        actionError = nil
        defer { isLeaving = false }
        do {
            try await sessionManager.authorizedRequest {
                try await self.groupsService.leaveGroup(id: self.groupId)
            }
            return true
        } catch {
            actionError = DomainErrorPresentation.message(for: error)
            return false
        }
    }

    func dismissActionError() {
        actionError = nil
    }

    func acknowledgeUnauthorized() {
        sessionManager.acknowledgeSessionExpired()
    }
}
