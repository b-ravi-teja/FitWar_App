import Foundation
import Observation

@MainActor
@Observable
final class ChatViewModel {
    private(set) var state: LoadState<[ChatMessage]> = .loading
    private(set) var isSending = false
    private(set) var isLive = false

    private var nextCursor: Date?
    private var nextCursorId: UUID?
    private var hasMore = true
    private var socketTask: Task<Void, Never>?

    private let groupId: UUID
    private let chat: ChatServiceProtocol
    private let realtime: RealtimeClientProtocol
    private let sessionManager: SessionManager

    init(
        groupId: UUID,
        chat: ChatServiceProtocol,
        realtime: RealtimeClientProtocol,
        sessionManager: SessionManager
    ) {
        self.groupId = groupId
        self.chat = chat
        self.realtime = realtime
        self.sessionManager = sessionManager
    }

    /// REST is the source of truth on every entry and every reconnect (§23).
    func load() async {
        state = .loading
        nextCursor = nil
        nextCursorId = nil
        hasMore = true
        do {
            let page = try await chat.fetchMessages(
                groupId: groupId, before: nil, beforeId: nil, limit: 30
            )
            nextCursor = page.nextCursor
            nextCursorId = page.nextCursorId
            hasMore = page.nextCursor != nil
            state = .loaded(page.items)
        } catch {
            state = LoadState.from(error)
        }
    }

    func loadMore() async {
        guard hasMore, let cursor = nextCursor, case .loaded(let existing) = state else { return }
        do {
            let page = try await chat.fetchMessages(
                groupId: groupId, before: cursor, beforeId: nextCursorId, limit: 30
            )
            nextCursor = page.nextCursor
            nextCursorId = page.nextCursorId
            hasMore = page.nextCursor != nil
            state = .loaded(existing + page.items)
        } catch {
            // Paging failure leaves what's already loaded on screen — losing the whole
            // history because one page failed would be worse than stopping here.
        }
    }

    func send(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        isSending = true
        defer { isSending = false }
        do {
            _ = try await chat.postMessage(groupId: groupId, content: trimmed)
            // Re-read rather than appending locally: the server assigns the id and
            // timestamp, and this keeps one ordering authority.
            await load()
        } catch {
            state = LoadState.from(error)
        }
    }

    func toggleReaction(messageId: UUID, emoji: String, currentlyReacted: Bool) async {
        do {
            try await chat.react(
                groupId: groupId, messageId: messageId, emoji: emoji, add: !currentlyReacted
            )
            await load()
        } catch {
            // Reactions are idempotent server-side; a failed toggle simply leaves the
            // last server state, which the reload would show anyway.
        }
    }

    /// Start listening. Events are treated as hints to re-read, never as data.
    func connectRealtime() {
        guard socketTask == nil, let token = sessionManager.currentAccessToken else { return }
        socketTask = Task { [weak self] in
            guard let self else { return }
            let stream = self.realtime.events(groupId: self.groupId, token: token)
            self.isLive = true
            for await event in stream {
                switch event {
                case .chatMessage, .systemMessage, .reactionChanged:
                    // Deliberately a refresh, not an append: delivery is not
                    // exactly-once, and re-reading makes a duplicate event harmless.
                    await self.load()
                case .gameStateChanged, .unknown:
                    break
                }
            }
            // Stream ended — the socket dropped. REST still works; the next appearance
            // or manual refresh reconciles.
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
