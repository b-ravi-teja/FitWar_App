import SwiftUI

/// Friend-activity feed row: dot + "Name did something" + relative time
/// (Home's "FRIEND ACTIVITY" list, Group's activity log).
struct ActivityRow: View {
    let who: String
    let what: String
    let when: String
    var dotColor: Color = FWColor.accent

    var body: some View {
        HStack(spacing: FWSpacing.md) {
            Circle()
                .fill(dotColor.opacity(0.9))
                .frame(width: 8, height: 8)

            (Text(who).font(FWTypography.bodyMedium).foregroundStyle(FWColor.textPrimary)
                + Text(" \(what)").font(FWTypography.bodySmall).foregroundStyle(FWColor.textDim))
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(when)
                .font(FWTypography.metaLabel)
                .foregroundStyle(FWColor.textDim2)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(who) \(what), \(when)")
    }
}
