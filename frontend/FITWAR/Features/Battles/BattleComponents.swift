import SwiftUI

/// The split "vs" bar from the design's Battle screen (design spec §3): one track,
/// two fills, the caller's share on the left.
///
/// It renders two server-supplied scores as a ratio. It decides nothing — a battle whose
/// bar leans left is not thereby won, and the screen's headline never reads this value.
struct BattleVersusBar: View {
    let myScore: Decimal
    let theirScore: Decimal
    let myShare: Double

    var body: some View {
        VStack(spacing: FWSpacing.xs) {
            GeometryReader { geo in
                HStack(spacing: 2) {
                    Capsule()
                        .fill(FWColor.accent)
                        .frame(width: max(2, geo.size.width * clampedShare))
                    Capsule()
                        .fill(FWColor.line2)
                }
            }
            .frame(height: 8)
            .animation(FWAnimation.progressFill, value: clampedShare)

            HStack {
                Text(FWNumber.compact(myScore))
                    .font(FWTypography.numericSmall)
                    .foregroundStyle(FWColor.accent)
                Spacer()
                Text(FWNumber.compact(theirScore))
                    .font(FWTypography.numericSmall)
                    .foregroundStyle(FWColor.textDim)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "You \(FWNumber.compact(myScore)), opponent \(FWNumber.compact(theirScore))"
        )
    }
}

private extension BattleVersusBar {
    var clampedShare: Double { max(0, min(1, myShare)) }
}

/// A countdown rendered from the server's own `time_remaining_seconds`.
///
/// The number is not recomputed from `end_at` against the device clock: the battle day
/// belongs to the battle's frozen timezone (§11), and two phones with different clocks
/// must not disagree about how long is left.
struct BattleCountdown: View {
    let seconds: Int

    var body: some View {
        Text(Self.format(seconds))
            .font(FWTypography.numericMedium)
            .foregroundStyle(seconds <= 3600 ? FWColor.orange : FWColor.textPrimary)
            .monospacedDigit()
            .accessibilityLabel("\(Self.format(seconds)) remaining")
    }

    static func format(_ seconds: Int) -> String {
        guard seconds > 0 else { return "TIME UP" }
        let days = seconds / 86_400
        let hours = (seconds % 86_400) / 3600
        let minutes = (seconds % 3600) / 60
        if days > 0 { return "\(days)D \(hours)H" }
        if hours > 0 { return "\(hours)H \(minutes)M" }
        return "\(minutes)M"
    }
}

/// One battle in the Battles tab list.
struct BattleCard: View {
    let battle: Battle
    var onTap: () -> Void = {}

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: FWSpacing.md) {
                HStack {
                    Text(headline)
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.eyebrow)
                        .foregroundStyle(FWColor.textDim2)
                    Spacer()
                    StatusBadge(text: badgeText, tone: badgeTone)
                }

                Text(battle.opponent?.displayName ?? "Opponent")
                    .font(FWTypography.titleSmall)
                    .foregroundStyle(FWColor.textPrimary)

                if let me = battle.me, let opponent = battle.opponent {
                    BattleVersusBar(
                        myScore: me.score,
                        theirScore: opponent.score,
                        myShare: battle.myShareOfScore
                    )
                }

                HStack(spacing: FWSpacing.md) {
                    Text("DAY \(battle.dayIndex) / \(battle.durationDays)")
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .foregroundStyle(FWColor.textDim2)
                    Spacer()
                    if battle.status == .active {
                        BattleCountdown(seconds: battle.timeRemainingSeconds)
                    }
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

    private var headline: String {
        "\(battle.activityType.displayName.uppercased()) · \(FWNumber.compact(battle.targetValue)) \(battle.unit.uppercased())/DAY"
    }

    /// Reads the server's status and outcome. Never a comparison of the two scores.
    private var badgeText: String {
        switch battle.status {
        case .pending: return battle.me?.status == .invited ? "INVITED" : "WAITING"
        case .active: return "LIVE"
        case .cancelled: return "CANCELLED"
        case .completed:
            switch battle.myOutcome {
            case .won: return "WON"
            case .lost, .out: return "LOST"
            case .left, .none: return "FINISHED"
            }
        }
    }

    private var badgeTone: StatusBadge.Tone {
        switch battle.status {
        case .active: return .accent
        case .pending: return .info
        case .cancelled: return .neutral
        case .completed: return battle.myOutcome == .won ? .gold : .danger
        }
    }
}

/// A challengeable squad-mate with their head-to-head record.
struct RivalRow: View {
    let rival: BattleRival
    var isBusy: Bool = false
    var onChallenge: () -> Void = {}

    var body: some View {
        HStack(spacing: FWSpacing.md) {
            AvatarView(size: 38, initials: String(rival.displayName.prefix(1)).uppercased())

            VStack(alignment: .leading, spacing: 2) {
                Text(rival.displayName)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textPrimary)
                Text(rival.record)
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.textDim2)
            }

            Spacer()

            if rival.liveBattleId != nil {
                // The server already refuses a second live battle with this player, so
                // the button is not offered rather than offered and rejected.
                StatusBadge(text: "IN BATTLE", tone: .accent)
            } else {
                Button(action: onChallenge) {
                    Text("CHALLENGE")
                        .font(FWTypography.metaLabel)
                        .tracking(FWTracking.metaLabel)
                        .padding(.horizontal, FWSpacing.md)
                        .padding(.vertical, FWSpacing.xs + 2)
                        .foregroundStyle(FWColor.onAccent)
                        .background(FWColor.accent)
                        .clipShape(Capsule())
                }
                .buttonStyle(FWPressableStyle())
                .disabled(isBusy)
                .opacity(isBusy ? 0.5 : 1)
            }
        }
        .padding(.vertical, FWSpacing.xs)
        .accessibilityElement(children: .combine)
    }
}
