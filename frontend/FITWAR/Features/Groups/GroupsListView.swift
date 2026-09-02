import SwiftUI

/// The SQUAD tab. Replaces the Phase 2 placeholder with the real Groups List
/// (design spec §20.7): a flat list of every group the user belongs to, a "+" to create
/// one, and a join-by-code entry for the design's invite flow.
struct GroupsListView: View {
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.groupsService) private var groupsService
    @Environment(\.challengesService) private var challengesService

    @State private var viewModel: GroupsListViewModel?
    @State private var path: [UUID] = []

    var body: some View {
        NavigationStack(path: $path) {
            content
                .background(FWColor.background)
                .navigationDestination(for: UUID.self) { groupId in
                    GroupDetailView(groupId: groupId, onLeft: { path.removeAll() })
                        .toolbar(.hidden, for: .navigationBar)
                }
                .toolbar(.hidden, for: .navigationBar)
        }
        .task {
            if viewModel == nil {
                viewModel = GroupsListViewModel(
                    groupsService: groupsService, sessionManager: sessionManager
                )
            }
            await viewModel?.load()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state {
        case .none, .loading:
            LoadingView(label: "Loading your squads…")
        case .loaded:
            loaded
        case .networkError:
            NetworkErrorView(onRetry: { Task { await viewModel?.load() } })
        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel?.load() } }
            )
        case .unauthorized:
            UnauthorizedView(onLogIn: { viewModel?.acknowledgeUnauthorized() })
        }
    }

    @ViewBuilder
    private var loaded: some View {
        if let viewModel {
            @Bindable var model = viewModel

            ScrollView {
                VStack(alignment: .leading, spacing: FWSpacing.xl) {
                    header

                    if viewModel.groups.isEmpty {
                        EmptyStateView(
                            title: "No squad yet.",
                            message: "Create a squad, or join one with a code from a friend.",
                            actionTitle: "CREATE A SQUAD",
                            action: { model.isCreating = true }
                        )
                        FITWARSecondaryButton(title: "JOIN WITH A CODE") {
                            model.isJoining = true
                        }
                    } else {
                        VStack(spacing: FWSpacing.md) {
                            ForEach(viewModel.groups) { group in
                                Button {
                                    path.append(group.id)
                                } label: {
                                    GroupCard(
                                        name: group.name,
                                        meta: group.metaLine,
                                        memberCount: group.memberCount
                                    )
                                }
                                .buttonStyle(FWPressableStyle())
                                .accessibilityLabel("\(group.name), \(group.metaLine)")
                            }
                        }

                        FITWARSecondaryButton(title: "JOIN WITH A CODE") {
                            model.isJoining = true
                        }
                    }
                }
                .padding(.horizontal, FWSpacing.screenHorizontal)
                .padding(.top, 62)
                .padding(.bottom, FWSpacing.xxl)
            }
            .refreshable { await viewModel.reload() }
            .sheet(isPresented: $model.isCreating) {
                CreateGroupSheet(viewModel: viewModel) { created in
                    path.append(created.id)
                }
            }
            .sheet(isPresented: $model.isJoining) {
                JoinGroupSheet(viewModel: viewModel) { joined in
                    path.append(joined.id)
                }
            }
        }
    }

    private var header: some View {
        HStack {
            Text("Squads")
                .font(FWTypography.displayMedium)
                .foregroundStyle(FWColor.textPrimary)
            Spacer()
            Button {
                viewModel?.isCreating = true
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(FWColor.onAccent)
                    .frame(width: 38, height: 38)
                    .background(FWColor.accent)
                    .clipShape(Circle())
            }
            .buttonStyle(FWPressableStyle())
            .accessibilityLabel("Create a squad")
        }
    }
}

/// Create-squad sheet. The group's timezone comes from the device rather than a picker:
/// it's the creator's own timezone, it's a real IANA identifier, and the owner can
/// change it later — asking for it up front would be a question with an obvious answer.
private struct CreateGroupSheet: View {
    @Bindable var viewModel: GroupsListViewModel
    let onCreated: (GroupSummary) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                SectionHeader(
                    eyebrow: "NEW SQUAD",
                    title: "Name your squad",
                    subtitle: "Everyone you invite competes on this squad's clock — \(TimeZone.current.identifier)."
                )

                FWTextField(
                    label: "Squad name",
                    text: $viewModel.newGroupName,
                    placeholder: "KITS FITNESS WAR",
                    errorMessage: viewModel.actionError
                )

                Spacer()

                FITWARPrimaryButton(
                    title: "CREATE SQUAD",
                    isLoading: viewModel.isSubmitting,
                    isDisabled: !viewModel.canCreate
                ) {
                    Task {
                        if let created = await viewModel.createGroup() {
                            dismiss()
                            onCreated(created)
                        }
                    }
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal + 4)
            .padding(.top, FWSpacing.xxxl)
            .padding(.bottom, FWSpacing.xxl)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(FWColor.background)
            .toolbar(.hidden, for: .navigationBar)
        }
        .presentationDetents([.medium])
        .onDisappear { viewModel.dismissActionError() }
    }
}

private struct JoinGroupSheet: View {
    @Bindable var viewModel: GroupsListViewModel
    let onJoined: (GroupSummary) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                SectionHeader(
                    eyebrow: "JOIN A SQUAD",
                    title: "Enter the join code",
                    subtitle: "Six characters, like K7-XR9. Case and the dash don't matter."
                )

                FWTextField(
                    label: "Join code",
                    text: $viewModel.joinCode,
                    placeholder: "K7-XR9",
                    errorMessage: viewModel.actionError
                )

                Spacer()

                FITWARPrimaryButton(
                    title: "JOIN SQUAD",
                    isLoading: viewModel.isSubmitting,
                    isDisabled: !viewModel.canJoin
                ) {
                    Task {
                        if let joined = await viewModel.joinGroup() {
                            dismiss()
                            onJoined(joined)
                        }
                    }
                }
            }
            .padding(.horizontal, FWSpacing.screenHorizontal + 4)
            .padding(.top, FWSpacing.xxxl)
            .padding(.bottom, FWSpacing.xxl)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(FWColor.background)
            .toolbar(.hidden, for: .navigationBar)
        }
        .presentationDetents([.medium])
        .onDisappear { viewModel.dismissActionError() }
    }
}
