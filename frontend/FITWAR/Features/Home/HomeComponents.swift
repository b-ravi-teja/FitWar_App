import SwiftUI

/// The one card that answers "what do I need to do today?".
///
/// Every number is server-computed: the target and day come from
/// `GET /challenges/{id}/progress/today`, the streak and rank from
/// `GET /challenges/{id}/me`. Nothing is derived locally, and the done/not-done state is
/// the server's `day_status` rather than a comparison the client makes.
struct TodaysMissionCard: View {
    let mission: TodaysMission
    var isBusy: Bool = false
    var onLog: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.lg) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: FWSpacing.xxs) {
                    Text("TODAY'S MISSION")
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.eyebrow)
                        .foregroundStyle(FWColor.textDim2)
                    Text(mission.challenge.name)
                        .font(FWTypography.titleMedium)
                        .foregroundStyle(FWColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: FWSpacing.md)
                statusBadge
            }

            HStack(alignment: .firstTextBaseline, spacing: FWSpacing.xs) {
                Text(FWNumber.compact(mission.progress.target))
                    .font(FWTypography.numericXL)
                    .foregroundStyle(mission.isDoneToday ? FWColor.accent : FWColor.textPrimary)
                Text(mission.progress.unit.uppercased())
                    .font(FWTypography.numericSmall)
                    .foregroundStyle(FWColor.textDim)
            }

            HStack(spacing: FWSpacing.md) {
                Text("DAY \(mission.progress.dayIndex) / \(mission.challenge.durationDays)")
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.textDim2)
                if mission.streak > 0 {
                    StreakBadge(days: mission.streak, isCompact: true)
                }
                Spacer()
                if let rank = mission.rank {
                    Text("RANK \(rank)")
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                }
            }

            if mission.isEliminated {
                Text("You're out of this war. You can still watch the leaderboard and "
                     + "join the next one.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
                    .fixedSize(horizontal: false, vertical: true)
            } else if mission.isDoneToday {
                Text("Today is banked. Come back tomorrow to keep the streak.")
                    .font(FWTypography.bodySmall)
                    .foregroundStyle(FWColor.textDim)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                FITWARPrimaryButton(title: "LOG TODAY", action: onLog)
                    .disabled(isBusy)
                    .opacity(isBusy ? 0.6 : 1)
            }

            if mission.warningCount > 0 && !mission.isEliminated {
                Text("\(mission.warningCount) WARNING\(mission.warningCount == 1 ? "" : "S") — "
                     + "complete today to reset.")
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.orange)
            }
        }
        .padding(FWSpacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(mission.isDoneToday ? FWColor.accent.opacity(0.4) : FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var statusBadge: some View {
        if mission.isEliminated {
            StatusBadge(text: "ELIMINATED", tone: .danger)
        } else if mission.isDoneToday {
            StatusBadge(text: "DONE", tone: .accent)
        } else {
            StatusBadge(text: "TO DO", tone: .warning)
        }
    }
}

/// A secondary war, when the user is in more than one.
struct MissionRow: View {
    let mission: TodaysMission
    var onTap: () -> Void = {}

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: FWSpacing.md) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(mission.challenge.name)
                        .font(FWTypography.bodyMedium)
                        .foregroundStyle(FWColor.textPrimary)
                        .lineLimit(1)
                    Text("DAY \(mission.progress.dayIndex) / \(mission.challenge.durationDays) · "
                         + "\(FWNumber.compact(mission.progress.target)) \(mission.progress.unit.uppercased())")
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                        .lineLimit(1)
                }
                Spacer(minLength: FWSpacing.sm)
                if mission.isEliminated {
                    StatusBadge(text: "OUT", tone: .danger)
                } else if mission.isDoneToday {
                    StatusBadge(text: "DONE", tone: .accent)
                } else {
                    StatusBadge(text: "TO DO", tone: .warning)
                }
            }
            .padding(FWSpacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(FWColor.surface)
            .overlay(
                RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                    .strokeBorder(FWColor.line)
            )
            .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        }
        .buttonStyle(FWPressableStyle())
        .accessibilityElement(children: .combine)
    }
}

/// Level and XP, straight from `GET /me/xp` — the level is server-computed (ADR 0008)
/// and the client only renders it.
struct LevelProgress: View {
    let xp: XPSummary

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.sm) {
            HStack {
                Text("LEVEL \(xp.level)")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow)
                    .foregroundStyle(FWColor.textDim2)
                Spacer()
                Text("\(FWNumber.compact(xp.xpIntoLevel)) / \(FWNumber.compact(xp.xpIntoLevel + xp.xpToNextLevel)) XP")
                    .font(FWTypography.numericSmall)
                    .foregroundStyle(FWColor.textDim)
            }
            FWProgressBar(progress: xp.levelProgress, height: 6)
        }
        .padding(FWSpacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Level \(xp.level), \(xp.xpIntoLevel) XP into this level")
    }
}
