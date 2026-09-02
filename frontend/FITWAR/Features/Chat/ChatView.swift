import SwiftUI

/// The group Chat tab. Small by design: text, the fixed reaction set, and system
/// messages the game emits — not a messaging platform.
struct ChatView: View {
    @State var viewModel: ChatViewModel
    @State private var draft = ""

    var body: some View {
        VStack(spacing: 0) {
            content
            composer
        }
        .background(FWColor.background)
        .task {
            await viewModel.load()
            // Additive: if this never connects, the history above is still correct.
            viewModel.connectRealtime()
        }
        .onDisappear { viewModel.disconnectRealtime() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loading:
            LoadingView(label: "Loading chat…")
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel.load() } })
        case .unauthorized:
            UnauthorizedView(onLogIn: {})
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Couldn't load chat",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel.load() } }
            )
        case .loaded(let messages):
            if messages.isEmpty {
                GenericStateView(
                    symbol: "bubble.left",
                    title: "No messages yet",
                    message: "Say something to your squad."
                )
            } else {
                messageList(messages)
            }
        }
    }

    private func messageList(_ messages: [ChatMessage]) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: FWSpacing.lg) {
                // Newest-first from the server, flipped so the newest sits at the bottom.
                ForEach(messages.reversed()) { message in
                    row(message)
                        .onAppear {
                            if message.id == messages.last?.id {
                                Task { await viewModel.loadMore() }
                            }
                        }
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.lg)
        }
        .defaultScrollAnchor(.bottom)
    }

    @ViewBuilder
    private func row(_ message: ChatMessage) -> some View {
        if message.messageType == .system {
            // A game event, rendered as a feed line rather than a person's message.
            Text(message.content.uppercased())
                .font(FWTypography.metaLabel)
                .foregroundStyle(FWColor.accent)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.vertical, FWSpacing.xs)
        } else {
            VStack(alignment: .leading, spacing: FWSpacing.xs) {
                Text(message.senderDisplayName ?? "Someone")
                    .font(FWTypography.metaLabel)
                    .foregroundStyle(FWColor.textDim2)
                Text(message.content)
                    .font(FWTypography.body)
                    .foregroundStyle(FWColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                reactionRow(message)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func reactionRow(_ message: ChatMessage) -> some View {
        HStack(spacing: FWSpacing.xs) {
            ForEach(message.reactions) { reaction in
                Button {
                    Task {
                        await viewModel.toggleReaction(
                            messageId: message.id,
                            emoji: reaction.emoji,
                            currentlyReacted: reaction.reactedByMe
                        )
                    }
                } label: {
                    Text("\(reaction.emoji) \(reaction.count)")
                        .font(FWTypography.metaLabel)
                        .padding(.horizontal, FWSpacing.sm)
                        .padding(.vertical, 4)
                        .background(reaction.reactedByMe ? FWColor.surface2 : FWColor.surface)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            Menu {
                ForEach(FWReaction.all, id: \.self) { emoji in
                    Button(emoji) {
                        Task {
                            await viewModel.toggleReaction(
                                messageId: message.id, emoji: emoji, currentlyReacted: false
                            )
                        }
                    }
                }
            } label: {
                Image(systemName: "plus.circle")
                    .font(.caption)
                    .foregroundStyle(FWColor.textDim2)
            }
        }
    }

    private var composer: some View {
        HStack(spacing: FWSpacing.sm) {
            FWTextField(label: "MESSAGE", text: $draft, placeholder: "Message your squad")
            Button {
                let text = draft
                draft = ""
                Task { await viewModel.send(text) }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(draft.isEmpty ? FWColor.textDim2 : FWColor.accent)
            }
            .disabled(draft.isEmpty || viewModel.isSending)
        }
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
    }
}
