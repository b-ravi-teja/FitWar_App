import SwiftUI

/// "CHALLENGE SOMEONE" — pick the squad, the activity and the length, then pick a rival.
///
/// The rival list, the head-to-head records and whether a rival is already busy all come
/// from the server. The target field can be left blank; the server fills in the
/// activity's default rather than the client inventing one.
struct CreateBattleView: View {
    var onCreated: (Battle) -> Void

    @Environment(\.battlesService) private var battlesService
    @Environment(\.groupsService) private var groupsService
    @Environment(SessionManager.self) private var sessionManager
    @Environment(\.dismiss) private var dismiss

    @State private var viewModel: CreateBattleViewModel?

    private static let durations = [1, 3, 7, 14, 30]

    var body: some View {
        NavigationStack {
            Group {
                if let viewModel {
                    content(viewModel)
                } else {
                    LoadingView(label: "Loading squads…")
                }
            }
            .background(FWColor.background)
            .navigationTitle("New battle")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.tint(FWColor.textDim)
                }
            }
        }
        .task {
            if viewModel == nil {
                viewModel = CreateBattleViewModel(
                    battles: battlesService,
                    groups: groupsService,
                    sessionManager: sessionManager
                )
            }
            await viewModel?.load()
        }
        .onChange(of: viewModel?.createdBattle) { _, battle in
            if let battle {
                viewModel?.clearCreatedBattle()
                onCreated(battle)
            }
        }
    }

    @ViewBuilder
    private func content(_ viewModel: CreateBattleViewModel) -> some View {
        switch viewModel.groupsState {
        case .loading:
            LoadingView(label: "Loading squads…")

        case .networkError:
            NetworkErrorView { Task { await viewModel.load() } }

        case .unauthorized:
            UnauthorizedView { Task { await sessionManager.logout() } }

        case .serverError(let message):
            GenericStateView(
                symbol: "exclamationmark.triangle",
                title: "Something went wrong",
                message: message,
                primaryActionTitle: "RETRY",
                primaryAction: { Task { await viewModel.load() } }
            )

        case .loaded(let groups):
            if groups.isEmpty {
                EmptyStateView(
                    title: "No squad yet.",
                    message: "Battles happen between squad-mates. Join or create a squad first."
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                form(viewModel, groups: groups)
            }
        }
    }

    private func form(
        _ viewModel: CreateBattleViewModel, groups: [GroupSummary]
    ) -> some View {
        @Bindable var model = viewModel
        return ScrollView {
            VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                if groups.count > 1 {
                    field("SQUAD") {
                        Picker("Squad", selection: $model.selectedGroupId) {
                            ForEach(groups) { group in
                                Text(group.name).tag(Optional(group.id))
                            }
                        }
                        .pickerStyle(.menu)
                        .tint(FWColor.accent)
                    }
                }

                field("ACTIVITY") {
                    Picker("Activity", selection: $model.activity) {
                        // Only activities Apple Health can measure — a battle verifies
                        // automatically, so offering push-ups would be a button the
                        // server rejects.
                        ForEach(CreateBattleViewModel.selectableActivities, id: \.self) {
                            Text($0.displayName).tag($0)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                FWTextField(
                    label: "DAILY TARGET",
                    text: $model.targetText,
                    placeholder: "\(FWNumber.compact(model.activity.defaultTarget)) \(model.activity.unit)",
                    keyboardType: .numberPad
                )

                field("LENGTH") {
                    Picker("Length", selection: $model.durationDays) {
                        ForEach(Self.durations, id: \.self) { days in
                            Text("\(days)D").tag(days)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                if let error = viewModel.actionError {
                    Text(error)
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.red)
                        .fixedSize(horizontal: false, vertical: true)
                }

                rivals(viewModel)
            }
            .padding(.horizontal, FWSpacing.screenHorizontal)
            .padding(.vertical, FWSpacing.xl)
        }
    }

    @ViewBuilder
    private func rivals(_ viewModel: CreateBattleViewModel) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.md) {
            Text("RIVALS")
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)

            switch viewModel.rivalsState {
            case .loading:
                ProgressView().tint(FWColor.accent)
            case .networkError:
                Text("Couldn't load your squad-mates. Pull to retry.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
            case .unauthorized, .serverError:
                Text("Couldn't load your squad-mates.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
            case .loaded(let rivals):
                if rivals.isEmpty {
                    Text("Nobody else is in this squad yet. Invite someone first.")
                        .font(FWTypography.bodySmall)
                        .foregroundStyle(FWColor.textDim)
                } else {
                    ForEach(rivals) { rival in
                        RivalRow(rival: rival, isBusy: viewModel.isSubmitting) {
                            Task { await viewModel.challenge(rival) }
                        }
                    }
                }
            }
        }
    }

    private func field(
        _ label: String, @ViewBuilder content: () -> some View
    ) -> some View {
        VStack(alignment: .leading, spacing: FWSpacing.sm) {
            Text(label)
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)
            content()
        }
    }
}
