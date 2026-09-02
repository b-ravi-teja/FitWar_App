import Foundation
import Observation

/// Backs the SQUAD tab's Groups List (design spec §20.7) — a flat list of every group
/// the user belongs to, plus the create and join-by-code actions that fill it.
@MainActor
@Observable
final class GroupsListViewModel {
    private(set) var state: LoadState<[GroupSummary]> = .loading

    var isCreating = false
    var isJoining = false
    var newGroupName = ""
    var joinCode = ""
    private(set) var actionError: String?
    private(set) var isSubmitting = false

    private let groupsService: GroupsServiceProtocol
    private let sessionManager: SessionManager

    init(groupsService: GroupsServiceProtocol, sessionManager: SessionManager) {
        self.groupsService = groupsService
        self.sessionManager = sessionManager
    }

    var groups: [GroupSummary] { state.value ?? [] }

    var canCreate: Bool {
        !newGroupName.trimmingCharacters(in: .whitespaces).isEmpty && !isSubmitting
    }

    var canJoin: Bool {
        !joinCode.trimmingCharacters(in: .whitespaces).isEmpty && !isSubmitting
    }

    func load() async {
        state = .loading
        await reload()
    }

    /// Refreshes without flashing the loading state — used after a create/join so the
    /// list updates in place rather than blanking out.
    func reload() async {
        do {
            let groups = try await sessionManager.authorizedRequest {
                try await self.groupsService.listGroups()
            }
            state = .loaded(groups)
        } catch {
            state = .from(error)
        }
    }

    func createGroup() async -> GroupSummary? {
        guard canCreate else { return nil }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }

        do {
            // The device's own timezone is the sensible default for a group the user is
            // creating right now, and it is a real IANA identifier — the backend rejects
            // anything that isn't (Architecture §11).
            let created = try await sessionManager.authorizedRequest {
                try await self.groupsService.createGroup(
                    name: self.newGroupName.trimmingCharacters(in: .whitespaces),
                    timezone: TimeZone.current.identifier
                )
            }
            newGroupName = ""
            isCreating = false
            await reload()
            return GroupSummary(
                id: created.id,
                name: created.name,
                timezone: created.timezone,
                memberCount: created.memberCount,
                activeChallengeCount: created.activeChallengeCount
            )
        } catch {
            actionError = DomainErrorPresentation.message(for: error)
            return nil
        }
    }

    func joinGroup() async -> GroupSummary? {
        guard canJoin else { return nil }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }

        do {
            let joined = try await sessionManager.authorizedRequest {
                try await self.groupsService.joinGroup(
                    code: self.joinCode.trimmingCharacters(in: .whitespaces)
                )
            }
            joinCode = ""
            isJoining = false
            await reload()
            return GroupSummary(
                id: joined.id,
                name: joined.name,
                timezone: joined.timezone,
                memberCount: joined.memberCount,
                activeChallengeCount: joined.activeChallengeCount
            )
        } catch {
            actionError = DomainErrorPresentation.message(for: error)
            return nil
        }
    }

    func dismissActionError() {
        actionError = nil
    }

    func acknowledgeUnauthorized() {
        sessionManager.acknowledgeSessionExpired()
    }
}
