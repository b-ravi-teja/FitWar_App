import Foundation
import Testing

@testable import FITWAR

@MainActor
private func makeSession() -> SessionManager {
    SessionManager(
        authService: MockAuthService(),
        keychain: MockKeychainStore(),
        apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
    )
}

@MainActor
struct ChatViewModelTests {
    private func makeSUT() -> (ChatViewModel, MockChatService, MockRealtimeClient) {
        let chat = MockChatService()
        let realtime = MockRealtimeClient()
        let sut = ChatViewModel(
            groupId: UUID(), chat: chat, realtime: realtime, sessionManager: makeSession()
        )
        return (sut, chat, realtime)
    }

    @Test func loadsHistoryFromRest() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(
            ChatPage(items: [MediaFixtures.message(content: "hi")], nextCursor: nil, nextCursorId: nil)
        )

        await sut.load()

        #expect(sut.state.value?.count == 1)
    }

    @Test func anEmptyChatIsLoadedNotAnError() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))

        await sut.load()

        #expect(sut.state.value?.isEmpty == true)
    }

    @Test func pagingSendsBothCursorParts() async {
        /// Timestamps tie, so the id half is what keeps the walk moving.
        let (sut, chat, _) = makeSUT()
        let cursorDate = Date(timeIntervalSince1970: 1_760_000_000)
        let cursorId = UUID()
        chat.pages = [
            ChatPage(items: [MediaFixtures.message(content: "a")], nextCursor: cursorDate, nextCursorId: cursorId),
            ChatPage(items: [MediaFixtures.message(content: "b")], nextCursor: nil, nextCursorId: nil),
        ]

        await sut.load()
        await sut.loadMore()

        #expect(sut.state.value?.count == 2)
        let second = chat.requestedCursors.last
        #expect(second?.0 == cursorDate)
        #expect(second?.1 == cursorId)
    }

    @Test func pagingStopsWhenThereIsNoCursor() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(
            ChatPage(items: [MediaFixtures.message()], nextCursor: nil, nextCursorId: nil)
        )
        await sut.load()
        let callsAfterLoad = chat.fetchCount

        await sut.loadMore()

        #expect(chat.fetchCount == callsAfterLoad, "no cursor means no further request")
    }

    @Test func sendingPostsThenRereadsFromTheServer() async {
        /// The server assigns id and ordering; appending locally would create a second
        /// ordering authority.
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))
        chat.postResult = .success(MediaFixtures.message(content: "sent"))
        await sut.load()
        let before = chat.fetchCount

        await sut.send("sent")

        #expect(chat.postedContents == ["sent"])
        #expect(chat.fetchCount > before, "should re-read after posting")
    }

    @Test func emptyDraftsAreNotSent() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))
        await sut.load()

        await sut.send("   ")

        #expect(chat.postedContents.isEmpty)
    }

    @Test func togglingAReactionAddsWhenNotReacted() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))
        let id = UUID()

        await sut.toggleReaction(messageId: id, emoji: "🔥", currentlyReacted: false)

        #expect(chat.reactions.map(\.2) == [true])
    }

    @Test func togglingAgainRemoves() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .success(ChatPage(items: [], nextCursor: nil, nextCursorId: nil))

        await sut.toggleReaction(messageId: UUID(), emoji: "🔥", currentlyReacted: true)

        #expect(chat.reactions.map(\.2) == [false])
    }

    @Test func networkFailureIsItsOwnState() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func aNonMemberSeesTheServerError() async {
        let (sut, chat, _) = makeSUT()
        chat.pageResult = .failure(
            APIError.server(status: 403, code: "NOT_A_MEMBER", detail: "nope")
        )

        await sut.load()

        guard case .serverError = sut.state else {
            Issue.record("expected serverError, got \(sut.state)")
            return
        }
    }
}

struct RealtimeEventParsingTests {
    @Test func parsesAChatMessage() {
        let event = RealtimeEvent.parse([
            "type": "chat_message",
            "message_id": "dd000000-0000-0000-0000-000000000001",
            "group_id": "ee000000-0000-0000-0000-000000000001",
        ])

        guard case .chatMessage = event else {
            Issue.record("expected chatMessage, got \(event)")
            return
        }
    }

    @Test func parsesAReactionChange() {
        let event = RealtimeEvent.parse([
            "type": "reaction_changed",
            "message_id": "dd000000-0000-0000-0000-000000000001",
        ])

        guard case .reactionChanged = event else {
            Issue.record("expected reactionChanged, got \(event)")
            return
        }
    }

    @Test func gameEventsCollapseToOneRefreshSignal() {
        /// Competitive state is never carried in a socket payload — the client re-reads.
        for type in ["score_changed", "warning_issued", "participant_eliminated", "challenge_completed"] {
            #expect(RealtimeEvent.parse(["type": type]) == .gameStateChanged)
        }
    }

    @Test func anUnknownEventIsIgnoredNotFatal() {
        /// A server that adds an event type must not break an older client.
        #expect(RealtimeEvent.parse(["type": "something_new_in_phase_9"]) == .unknown)
        #expect(RealtimeEvent.parse([:]) == .unknown)
    }

    @Test func aMalformedIdDoesNotCrash() {
        #expect(RealtimeEvent.parse(["type": "chat_message", "message_id": "not-a-uuid"]) == .unknown)
    }
}

@MainActor
struct RealtimeReconnectTests {
    @Test func aDroppedSocketLeavesTheHistoryIntact() async {
        /// Realtime is additive: losing it must not lose data.
        let chat = MockChatService()
        let realtime = MockRealtimeClient()
        chat.pageResult = .success(
            ChatPage(items: [MediaFixtures.message(content: "durable")], nextCursor: nil, nextCursorId: nil)
        )
        let sut = ChatViewModel(
            groupId: UUID(), chat: chat, realtime: realtime, sessionManager: makeSession()
        )
        await sut.load()

        // The mock stream finishes immediately, modelling a socket that drops.
        sut.connectRealtime()
        try? await Task.sleep(nanoseconds: 50_000_000)

        #expect(sut.state.value?.first?.content == "durable")
    }

    @Test func disconnectingIsSafeWhenNeverConnected() async {
        let chat = MockChatService()
        let realtime = MockRealtimeClient()
        let sut = ChatViewModel(
            groupId: UUID(), chat: chat, realtime: realtime, sessionManager: makeSession()
        )

        sut.disconnectRealtime()

        #expect(realtime.disconnectCount == 1)
    }
}
