import Foundation
import Observation

/// The live battle screen, and the Victory/Defeat screens it resolves into.
///
/// The one rule this type exists to honour: **the client never decides the result.**
/// `phase` below reads the server's `status`, `myOutcome` and `winnerUserId`; it does
/// not compare the two scores it is holding. A screen that computed its own winner
/// could disagree with the ledger, and the ledger is what paid out.
@MainActor
@Observable
final class BattleDetailViewModel {
    /// Every state the design's battle flow can be in (§17). Loading, pending,
    /// active, finished and failed are distinct — none of them overlap, so the view
    /// cannot render two at once.
    enum Phase: Equatable {
        case loading
        /// Waiting for the opponent to answer an invitation the caller sent.
        case awaitingOpponent(Battle)
        /// An invitation waiting on the caller.
        case invited(Battle)
        /// Live. `mineIsDone` is today's own day, not the whole battle.
        case active(Battle, mineIsDone: Bool)
        case victory(Battle)
        case defeat(Battle)
        case cancelled(Battle)
        case networkFailure
        case unauthorized
        case serverError(String)
    }

    private(set) var phase: Phase = .loading
    private(set) var actionError: String?
    private(set) var isSubmitting = false
    /// Whether the live socket is attached. Purely informational — the screen is fully
    /// functional without it.
    private(set) var isLive = false

    private let battleId: UUID
    private let battles: BattlesServiceProtocol
    private let health: HealthKitServicing
    private let realtime: RealtimeClientProtocol
    private let sessionManager: SessionManager
    private var socketTask: Task<Void, Never>?

    init(
        battleId: UUID,
        battles: BattlesServiceProtocol,
        health: HealthKitServicing,
        realtime: RealtimeClientProtocol,
        sessionManager: SessionManager
    ) {
        self.battleId = battleId
        self.battles = battles
        self.health = health
        self.realtime = realtime
        self.sessionManager = sessionManager
    }

    var battle: Battle? {
        switch phase {
        case .awaitingOpponent(let battle),
             .invited(let battle),
             .active(let battle, _),
             .victory(let battle),
             .defeat(let battle),
             .cancelled(let battle):
            return battle
        case .loading, .networkFailure, .unauthorized, .serverError:
            return nil
        }
    }

    func load() async {
        await reload(showLoading: true)
    }

    /// Read authoritative state and derive the phase from it — the "server state wins
    /// after refresh" rule (§17), applied on every path including realtime.
    func reload(showLoading: Bool = false) async {
        if showLoading { phase = .loading }
        do {
            apply(
                try await sessionManager.authorizedRequest {
                    try await battles.fetchBattle(id: battleId)
                }
            )
        } catch {
            phase = Self.failurePhase(for: error)
        }
    }

    private func apply(_ battle: Battle) {
        switch battle.status {
        case .pending:
            phase = battle.me?.status == .invited
                ? .invited(battle)
                : .awaitingOpponent(battle)
        case .active:
            phase = .active(battle, mineIsDone: (battle.me?.daysCompleted ?? 0) >= battle.dayIndex)
        case .completed:
            // Read, never computed. `myOutcome` is the server's verdict; if it is
            // somehow absent the screen stays on the live view rather than guessing.
            switch battle.myOutcome {
            case .won: phase = .victory(battle)
            case .lost, .out: phase = .defeat(battle)
            case .left, .none:
                phase = .active(battle, mineIsDone: true)
            }
        case .cancelled:
            phase = .cancelled(battle)
        }
    }

    private static func failurePhase(for error: Error) -> Phase {
        switch LoadState<Battle>.from(error) {
        case .networkError: return .networkFailure
        case .unauthorized: return .unauthorized
        case .serverError(let message): return .serverError(message)
        case .loading, .loaded: return .serverError("Something went wrong.")
        }
    }

    // MARK: - Actions

    func accept() async {
        await act { try await self.battles.accept(battleId: self.battleId) }
    }

    func decline() async {
        await act { try await self.battles.decline(battleId: self.battleId) }
    }

    private func act(_ operation: @escaping () async throws -> Battle) async {
        guard !isSubmitting else { return }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }
        do {
            apply(try await sessionManager.authorizedRequest(operation))
        } catch {
            actionError = BattleErrorPresentation.message(for: error)
        }
    }

    /// Read today's activity and submit it. The server verifies and scores it — this
    /// method reads a number from HealthKit and sends it, and inspects neither the
    /// target nor the outcome on the way.
    func submitTodaysEvidence() async {
        guard case .active(let battle, _) = phase, !isSubmitting else { return }
        isSubmitting = true
        actionError = nil
        defer { isSubmitting = false }

        do {
            // The window is the server's, computed from the battle's frozen timezone.
            // Deriving it from the device calendar is exactly the §11 mistake — a
            // player abroad would read the wrong day and lose it.
            let evidence = try await health.readEvidence(
                for: battle.activityType,
                start: battle.startAt,
                end: min(battle.endAt, Date())
            )
            let response = try await sessionManager.authorizedRequest {
                try await battles.submitEvidence(
                    battleId: battle.id,
                    request: SubmitVerificationRequest(
                        provider: .appleHealth, evidence: evidence
                    )
                )
            }
            // The reply carries the authoritative battle, including the finalization
            // this submission may have triggered.
            apply(response.battle)
        } catch HealthKitError.unavailable {
            actionError = "Apple Health isn't available on this device."
        } catch HealthKitError.unsupportedMetric {
            actionError = "This battle's activity can't be measured from health data."
        } catch HealthKitError.notAuthorized {
            actionError = "FITWAR can't read your health data. Check Settings › Privacy "
                + "& Security › Health › FITWAR."
        } catch is HealthKitError {
            // Product copy only — a framework error string never reaches a player.
            actionError = "Couldn't read your activity. Try again."
        } catch {
            actionError = BattleErrorPresentation.message(for: error)
        }
    }

    // MARK: - Realtime

    /// Attach the battle socket. Events are hints to re-read, never data: the payloads
    /// carry no scores, and REST decides what the screen shows.
    func connectRealtime() {
        guard socketTask == nil, let token = sessionManager.currentAccessToken else { return }
        socketTask = Task { [weak self] in
            guard let self else { return }
            let stream = self.realtime.events(battleId: self.battleId, token: token)
            self.isLive = true
            for await event in stream {
                switch event {
                case .battleChanged, .battleCompleted, .battleInvited:
                    await self.reload()
                case .chatMessage, .systemMessage, .reactionChanged, .gameStateChanged, .unknown:
                    break
                }
            }
            // The socket dropped. Nothing is lost — the next reload reconciles.
            self.isLive = false
            self.socketTask = nil
        }
    }

    func disconnectRealtime() {
        socketTask?.cancel()
        socketTask = nil
        realtime.disconnect()
        isLive = false
    }
}
