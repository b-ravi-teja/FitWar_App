import Foundation
import Observation

/// One active challenge, reduced to what Home needs to answer "what do I do today?".
struct TodaysMission: Identifiable, Sendable, Equatable {
    let challenge: ChallengeSummary
    let progress: DailyProgress
    let gameState: MyChallengeGameState?

    var id: UUID { challenge.id }

    /// Today is settled — the target was met and verified. Read from the server's day
    /// status, never inferred from a value the client happens to hold.
    var isDoneToday: Bool { progress.status == .completed }

    var streak: Int { gameState?.currentStreak ?? 0 }
    var rank: Int? { gameState?.rank }
    var isEliminated: Bool { gameState?.status == .eliminated }
    var warningCount: Int { gameState?.warnings.count ?? 0 }
}

/// Home: the answer to "what do I need to do today?", assembled from endpoints that
/// already exist. It creates no game state of its own — every number here was computed
/// server-side and is only being surfaced one screen earlier than before.
@MainActor
@Observable
final class HomeViewModel {
    private(set) var state: LoadState<[TodaysMission]> = .loading
    private(set) var xp: XPSummary?

    private let challenges: ChallengesServiceProtocol
    private let games: GameServiceProtocol
    private let sessionManager: SessionManager

    init(
        challenges: ChallengesServiceProtocol,
        games: GameServiceProtocol,
        sessionManager: SessionManager
    ) {
        self.challenges = challenges
        self.games = games
        self.sessionManager = sessionManager
    }

    var missions: [TodaysMission] { state.value ?? [] }

    /// The one mission Home leads with: whatever still needs doing today, else the first
    /// active challenge. Sorting by "not done" first means the CTA is always actionable
    /// when there is anything to act on.
    var primary: TodaysMission? {
        missions.first(where: { !$0.isDoneToday && !$0.isEliminated }) ?? missions.first
    }

    var others: [TodaysMission] {
        guard let primary else { return [] }
        return missions.filter { $0.id != primary.id }
    }

    var allDoneToday: Bool {
        !missions.isEmpty && missions.allSatisfy { $0.isDoneToday || $0.isEliminated }
    }

    func load() async {
        state = .loading
        await reload()
    }

    /// Re-read without clearing the screen — used on return from Verify, so the new day
    /// status comes from the server rather than being patched in locally.
    func reload() async {
        do {
            let active = try await sessionManager.authorizedRequest {
                try await challenges.listMyChallenges(status: .active)
            }
            // Only challenges the caller is actually still playing produce a mission.
            let mine = active.filter { $0.myStatus != nil && $0.myStatus != .left }

            var built: [TodaysMission] = []
            for challenge in mine {
                // Both calls are per-challenge and already exist; a beta user has a
                // handful of active challenges, so this stays a small, bounded fan-out.
                guard let progress = try? await sessionManager.authorizedRequest({
                    try await challenges.fetchTodayProgress(challengeId: challenge.id)
                }) else { continue }
                let gameState = try? await sessionManager.authorizedRequest {
                    try await games.fetchMyGameState(challengeId: challenge.id)
                }
                built.append(
                    TodaysMission(challenge: challenge, progress: progress, gameState: gameState)
                )
            }
            state = .loaded(built)
            // XP is supplementary: Home still works if it fails.
            xp = try? await sessionManager.authorizedRequest { try await games.fetchXPSummary() }
        } catch {
            state = LoadState.from(error)
        }
    }
}
