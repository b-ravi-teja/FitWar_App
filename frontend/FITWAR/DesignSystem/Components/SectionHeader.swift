import SwiftUI

/// The eyebrow-label + headline pattern repeated on nearly every screen in the
/// design (e.g. "STEP 1/3" + "What do you want to compete in?").
struct SectionHeader: View {
    let eyebrow: String
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.sm) {
            Text(eyebrow)
                .font(FWTypography.eyebrowLabel)
                .tracking(FWTracking.eyebrow)
                .foregroundStyle(FWColor.textDim2)
                .textCase(.uppercase)
                .accessibilityHidden(true) // decorative eyebrow; title carries the meaning

            Text(title)
                .font(FWTypography.displayMedium)
                .foregroundStyle(FWColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if let subtitle {
                Text(subtitle)
                    .font(FWTypography.bodyMedium)
                    .foregroundStyle(FWColor.textDim)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
