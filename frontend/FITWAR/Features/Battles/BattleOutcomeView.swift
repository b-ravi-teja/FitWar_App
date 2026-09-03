import SwiftUI

/// Victory (design screen 20) and Defeat (screen 29), which mirror each other.
///
/// `didWin` is passed in from the server's `my_outcome`. This view compares nothing:
/// hand it a battle where the caller scored more and `didWin: false`, and it renders
/// defeat, because the server is what decided.
struct BattleOutcomeView: View {
    let battle: Battle
    let didWin: Bool
    var onDone: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            VStack(alignment: .leading, spacing: FWSpacing.sm) {
                Text("1V1 COMPLETE")
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow)
                    .foregroundStyle(FWColor.textDim2)
                Text(didWin ? "VICTORY" : "BATTLE LOST")
                    .font(FWTypography.heroHeadline)
                    .foregroundStyle(didWin ? FWColor.accent : FWColor.textPrimary)
            }

            finalScores

            // Only the winner is paid, and only the amount the ledger recorded —
            // §20.11 gives the loser no XP block at all, so there is none to render.
            if didWin, let awarded = battle.myXPAwarded {
                xpPayout(awarded)
            }

            Spacer()

            FITWARPrimaryButton(title: didWin ? "CHALLENGE AGAIN" : "REMATCH", action: onDone)
            FITWARTextButton(title: "BACK TO BATTLES", action: onDone)
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, FWSpacing.xxl)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
    }

    private var finalScores: some View {
        VStack(spacing: FWSpacing.md) {
            scoreRow(battle.me, label: "YOU", isWinner: didWin)
            Divider().overlay(FWColor.line)
            scoreRow(
                battle.opponent,
                label: battle.opponent?.displayName.uppercased() ?? "OPPONENT",
                isWinner: !didWin
            )
        }
        .padding(FWSpacing.lg)
        .background(FWColor.surface)
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous)
                .strokeBorder(FWColor.line)
        )
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large - 2, style: .continuous))
    }

    private func scoreRow(_ side: BattleSide?, label: String, isWinner: Bool) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(FWTypography.eyebrowLabel)
                    .tracking(FWTracking.eyebrow)
                    .foregroundStyle(FWColor.textDim2)
                Text("\(side?.daysCompleted ?? 0) / \(battle.durationDays) DAYS")
                    .font(FWTypography.metaLabel)
                    .tracking(FWTracking.metaLabel)
                    .foregroundStyle(FWColor.textDim)
            }
            Spacer()
            Text(FWNumber.compact(side?.score ?? 0))
                .font(FWTypography.numericXL)
                .foregroundStyle(isWinner ? FWColor.accent : FWColor.textPrimary)
        }
        .accessibilityElement(children: .combine)
    }

    private func xpPayout(_ awarded: Int) -> some View {
        HStack {
            Text("BATTLE WIN")
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)
            Spacer()
            // The server read this straight back out of the XP ledger — the client
            // holds no copy of the award amount to print.
            Text("+\(awarded)")
                .font(FWTypography.numericXL)
                .foregroundStyle(FWColor.accent)
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
    }
}
