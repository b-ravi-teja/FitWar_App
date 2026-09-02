import Foundation
import Observation

@MainActor
@Observable
final class LeaderboardViewModel {
    private(set) var state: LoadState<Leaderboard> = .loading

    private let challengeId: UUID
    private let games: GameServiceProtocol

    init(challengeId: UUID, games: GameServiceProtocol) {
        self.challengeId = challengeId
        self.games = games
    }

    func load() async {
        state = .loading
        do {
            state = .loaded(try await games.fetchLeaderboard(challengeId: challengeId))
        } catch {
            state = LoadState.from(error)
        }
    }
}

/// Sub-label copy for a leaderboard row.
///
/// The status/outcome the server sent decides this — the client never infers that
/// someone is out, or who won, from scores it happens to be holding.
enum LeaderboardRowPresentation {
    static func subLabel(for entry: LeaderboardEntry, isFinal: Bool) -> String {
        if let outcome = entry.outcome {
            switch outcome {
            case .won: return isFinal ? "WON" : "STILL IN"
            case .lost: return "FINISHED"
            case .out: return "ELIMINATED"
            case .left: return "LEFT"
            }
        }
        switch entry.status {
        case .eliminated: return "ELIMINATED"
        case .left: return "LEFT"
        case .completed: return "FINISHED"
        case .active:
            return entry.currentStreak > 0 ? "\(entry.currentStreak) DAY STREAK" : "NO STREAK"
        }
    }
}
