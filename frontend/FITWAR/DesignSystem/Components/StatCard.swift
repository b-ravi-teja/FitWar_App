import SwiftUI

/// One cell of the Profile stats grid (2x2, hairline-divided) — big Archivo number
/// over a small tracked JetBrains Mono label.
struct StatCard: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxs) {
            Text(value)
                .font(FWTypography.titleLarge)
                .foregroundStyle(FWColor.textPrimary)
            Text(label)
                .font(FWTypography.metaLabel)
                .tracking(FWTracking.metaLabel)
                .textCase(.uppercase)
                .foregroundStyle(FWColor.textDim2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(FWSpacing.lg)
        .background(FWColor.background)
        .accessibilityElement(children: .combine)
    }
}

/// The 2x2 hairline-divided grid itself, matching the prototype's
/// `grid-template-columns:1fr 1fr;gap:1px;background:var(--line)` trick.
struct StatCardGrid: View {
    let stats: [(value: String, label: String)]

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 1), GridItem(.flexible(), spacing: 1)], spacing: 1) {
            ForEach(stats.indices, id: \.self) { index in
                StatCard(value: stats[index].value, label: stats[index].label)
            }
        }
        .background(FWColor.line)
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous)
                .strokeBorder(FWColor.line)
        )
    }
}
