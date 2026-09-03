import Foundation

/// Live group events over WebSocket (Architecture §10, §23).
///
/// Realtime is **additive**. Nothing here is required for correctness: every event the
/// socket delivers is also obtainable over REST, and the app is fully usable if this
/// never connects. Three consequences shape the design:
///
/// - Delivery is **not exactly-once**. Events may arrive twice or not at all, so
///   consumers must be idempotent and reconcile against REST rather than accumulating
///   socket deltas as if they were the record.
/// - On (re)connect the consumer refreshes authoritative state over REST, which is how
///   anything missed while disconnected is recovered.
/// - Failure is silent and non-fatal: a socket that cannot connect leaves the app in
///   exactly the state it would have been in without realtime at all.
enum RealtimeEvent: Sendable, Equatable {
    case chatMessage(messageId: UUID, groupId: UUID)
    case reactionChanged(messageId: UUID)
    case systemMessage(messageId: UUID, groupId: UUID)
    /// A game event (score, warning, elimination) — the client re-reads REST rather than
    /// trusting a payload to carry competitive state.
    case gameStateChanged
    /// Someone challenged the caller's squad. Carries only the battle's identity —
    /// the Battles tab reloads over REST to find out what it is.
    case battleInvited(battleId: UUID)
    /// A battle moved (accepted, declined, or a side posted evidence). Deliberately
    /// carries no scores: the server never puts competitive state on the wire here, so
    /// the only correct response is to re-read.
    case battleChanged(battleId: UUID)
    /// A battle was finalized. `winnerUserId` is the server's verdict, not a hint —
    /// but the screen still refreshes over REST before showing Victory or Defeat,
    /// because delivery is not exactly-once and REST is the record.
    case battleCompleted(battleId: UUID, winnerUserId: UUID?)
    case unknown

    /// Parsing is deliberately forgiving: an unrecognised event becomes `.unknown`
    /// rather than an error, so a server that adds an event type never breaks an old client.
    static func parse(_ json: [String: Any]) -> RealtimeEvent {
        let type = json["type"] as? String ?? ""
        let messageId = (json["message_id"] as? String).flatMap(UUID.init)
        let groupId = (json["group_id"] as? String).flatMap(UUID.init)
        let battleId = (json["battle_id"] as? String).flatMap(UUID.init)
        switch type {
        case "chat_message":
            if let messageId, let groupId { return .chatMessage(messageId: messageId, groupId: groupId) }
        case "system_message":
            if let messageId, let groupId { return .systemMessage(messageId: messageId, groupId: groupId) }
        case "reaction_changed":
            if let messageId { return .reactionChanged(messageId: messageId) }
        case "score_changed", "warning_issued", "participant_eliminated", "challenge_completed":
            return .gameStateChanged
        case "battle_invited":
            if let battleId { return .battleInvited(battleId: battleId) }
        case "battle_status_changed", "battle_progress":
            if let battleId { return .battleChanged(battleId: battleId) }
        case "battle_completed":
            if let battleId {
                return .battleCompleted(
                    battleId: battleId,
                    winnerUserId: (json["winner_user_id"] as? String).flatMap(UUID.init)
                )
            }
        default:
            return .unknown
        }
        return .unknown
    }
}

protocol RealtimeClientProtocol: Sendable {
    /// Connect and stream events. The stream simply finishes when the socket drops —
    /// the caller decides whether to reconnect.
    func events(groupId: UUID, token: String) -> AsyncStream<RealtimeEvent>
    /// The battle equivalent. A separate socket rather than a filter on the group one:
    /// the server authorizes battle channels against `battle_participant`, so a
    /// squad-mate who isn't playing is refused (Architecture §24).
    func events(battleId: UUID, token: String) -> AsyncStream<RealtimeEvent>
    func disconnect()
}

final class WebSocketRealtimeClient: RealtimeClientProtocol, @unchecked Sendable {
    private let baseURL: URL
    private var task: URLSessionWebSocketTask?

    init(baseURL: URL = AppConfig.apiBaseURL) {
        self.baseURL = baseURL
    }

    func events(groupId: UUID, token: String) -> AsyncStream<RealtimeEvent> {
        stream(path: "api/v1/ws/groups/\(groupId.uuidString)", token: token)
    }

    func events(battleId: UUID, token: String) -> AsyncStream<RealtimeEvent> {
        stream(path: "api/v1/ws/battles/\(battleId.uuidString)", token: token)
    }

    private func stream(path: String, token: String) -> AsyncStream<RealtimeEvent> {
        AsyncStream { continuation in
            guard var components = URLComponents(
                url: baseURL.appendingPathComponent(path),
                resolvingAgainstBaseURL: false
            ) else {
                continuation.finish()
                return
            }
            // ws:// for http://, wss:// for https:// — the socket follows the API's scheme.
            components.scheme = baseURL.scheme == "https" ? "wss" : "ws"
            // The token rides as a query item because a WebSocket handshake cannot carry
            // custom headers. It is a short-lived access token, and the server authorizes
            // group membership before accepting the connection.
            components.queryItems = [URLQueryItem(name: "token", value: token)]
            guard let url = components.url else {
                continuation.finish()
                return
            }

            let socket = URLSession.shared.webSocketTask(with: url)
            self.task = socket
            socket.resume()

            func receive() {
                socket.receive { result in
                    switch result {
                    case .success(.string(let text)):
                        if let data = text.data(using: .utf8),
                           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                            continuation.yield(RealtimeEvent.parse(json))
                        }
                        receive()
                    case .success:
                        receive()
                    case .failure:
                        // Refused, dropped, or the network went away. Ending the stream
                        // is the whole error path — the consumer falls back to REST.
                        continuation.finish()
                    }
                }
            }
            receive()

            continuation.onTermination = { @Sendable _ in
                socket.cancel(with: .goingAway, reason: nil)
            }
        }
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
    }
}
