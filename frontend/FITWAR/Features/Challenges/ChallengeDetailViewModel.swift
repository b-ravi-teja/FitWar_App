import Foundation
import Observation

/// Backs the Challenge Detail screen.
///
/// Every status shown here comes from the server. The view never decides whether a
/// challenge is active, whether a participant is eliminated, or what "today" is — it
/// renders `ChallengeDetail` and `DailyProgress` exactly as returned.
@MainActor
@Observable
final class ChallengeDetailViewModel {
    struct Content: Equatable {
        var challenge: ChallengeDetail
        /// Nil when the caller isn't a participant, or the challenge isn't running —
        /// there is no "today" to report in either case.
        var todayProgress: DailyProgress?
    }

    private(set) var state: LoadState<Content> = .loading
    private(set) var actionError: String?
    private(set) var isMutating = false

    let challengeId: UUID
    private let challengesService: ChallengesServiceProtocol
    private let sessionManager: SessionManager
    private let currentUserId: UUID?

    init(
        challengeId: UUID,
        challengesService: ChallengesServiceProtocol,
        sessionManager: SessionManager,
        currentUserId: UUID?
    ) {
        self.challengeId = challengeId
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
            let challenge = try await sessionManager.authorizedRequest {
                try await self.challengesService.fetchChallenge(id: self.challengeId)
            }
            state = .loaded(
                Content(challenge: challenge, todayProgress: await fetchTodayIfApplicable(challenge))
            )
        } catch {
            state = .from(error)
        }
    }

    /// Today's progress only exists for an active participant. Asking otherwise would
    /// get a well-formed 403/409 back — this avoids turning an expected condition into
    /// an error the screen has to explain away.
    private func fetchTodayIfApplicable(_ challenge: ChallengeDetail) async -> DailyProgress? {
        guard challenge.status == .active, challenge.myStatus == .active else { return nil }
        return try? await sessionManager.authorizedRequest {
            try await self.challengesService.fetchTodayProgress(challengeId: self.challengeId)
        }
    }

    func join() async {
        await mutate {
            _ = try await self.challengesService.joinChallenge(id: self.challengeId)
        }
    }

    func leave() async {
        await mutate {
            try await self.challengesService.leaveChallenge(id: self.challengeId)
        }
    }

    private func mutate(_ operation: @escaping () async throws -> Void) async {
        isMutating = true
        actionError = nil
        defer { isMutating = false }
        do {
            try await sessionManager.authorizedRequest { try await operation() }
            // Always re-read rather than patching local state: the server owns the
            // participant count, my status, and everything derived from them.
            await reload()
        } catch {
            actionError = DomainErrorPresentation.message(for: error)
        }
    }

    func dismissActionError() {
        actionError = nil
    }

    func acknowledgeUnauthorized() {
        sessionManager.acknowledgeSessionExpired()
    }
}
