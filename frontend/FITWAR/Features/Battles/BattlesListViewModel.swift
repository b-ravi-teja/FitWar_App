import Foundation
import Observation

/// The BATTLES tab: the caller's live battle, outstanding invitations, and history.
///
/// Everything shown is read from the server. This type holds no scores of its own, no
/// timers it runs, and no notion of who is winning — it loads `Battle` values and hands
/// them to the view.
@MainActor
@Observable
final class BattlesListViewModel {
    private(set) var state: LoadState<[Battle]> = .loading
    private(set) var actionError: String?
    private(set) var isSubmitting = false

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

    var all: [Battle] { state.value ?? [] }

    /// The one live battle the design's Battles screen leads with. There can only be
    /// one per opponent, and in practice one at a time — the server refuses a second
    /// live battle with the same player.
    var live: Battle? { all.first { $0.status == .active } }

    /// Invitations waiting on the caller. The challenger's own pending battle is not an
    /// invitation to them — it is waiting on the other side.
    var invitations: [Battle] {
        all.filter { $0.status == .pending && $0.me?.status == .invited }
    }

    /// Invitations the caller sent that nobody has answered yet.
    var awaitingOpponent: [Battle] {
        all.filter { $0.status == .pending && $0.me?.status != .invited }
    }

    var history: [Battle] {
        all.filter { $0.status == .completed || $0.status == .cancelled }
    }

    var hasAnything: Bool { !all.isEmpty }

    func load() async {
        state = .loading
        await reload()
    }

    /// Re-read without clearing the screen. This is also the realtime path: an event is
    /// a hint that something changed, never the change itself.
    func reload() async {
        actionError = nil
        do {
            state = .loaded(
                try await sessionManager.authorizedRequest {
                    try await battles.fetchBattles(status: nil)
                }
            )
        } catch {
            state = LoadState.from(error)
        }
    }

    func accept(_ battle: Battle) async {
        await act { try await self.battles.accept(battleId: battle.id) }
    }

    func decline(_ battle: Battle) async {
        await act { try await self.battles.decline(battleId: battle.id) }
    }

    private func act(_ operation: @escaping () async throws -> Battle) async {
        guard !isSubmitting else { return }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }
        do {
            _ = try await sessionManager.authorizedRequest(operation)
            // The reply already carries the new battle, but the list is re-read anyway:
            // accepting changes more than one row, and the server is the record.
            await reload()
        } catch {
            actionError = BattleErrorPresentation.message(for: error)
        }
    }
}

/// Backend error `code` → copy, for the battle domain.
///
/// `code` is the stable contract (Architecture §12); `detail` is not promised to be
/// user-facing copy, so every code a player can realistically hit gets a line here.
enum BattleErrorPresentation {
    static func message(for error: Error) -> String {
        guard case .server(_, let code, let detail)? = error as? APIError else {
            return DomainErrorPresentation.message(for: error)
        }
        switch code {
        case "ALREADY_PENDING_WITH_USER":
            return "You already have a battle running with this player."
        case "OPPONENT_NOT_AVAILABLE":
            return "You can't battle that player."
        case "GROUP_REQUIRED":
            return "You share more than one squad with them — pick which one."
        case "NOT_INVITED":
            return "This invitation isn't yours to answer."
        case "BATTLE_NOT_ACTIVE":
            return "This battle isn't running, so it can't take evidence."
        case "BATTLE_NOT_PENDING":
            return "This battle has already started."
        case "BATTLE_NOT_FOUND":
            return "That battle no longer exists."
        case "INVALID_BATTLE_CONFIG":
            return detail
        default:
            return DomainErrorPresentation.message(for: error)
        }
    }
}
