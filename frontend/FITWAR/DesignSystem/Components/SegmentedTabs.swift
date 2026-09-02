import SwiftUI

/// Pill segmented control (Challenges' ACTIVE/COMPLETED, Group's ROSTER/FEED/CHAT) —
/// `background:var(--srf);border-radius:12px;padding:4px` with a filled active segment.
struct SegmentedTabs: View {
    let options: [String]
    @Binding var selection: String

    var body: some View {
        HStack(spacing: FWSpacing.xxs) {
            ForEach(options, id: \.self) { option in
                let isActive = option == selection
                Button {
                    selection = option
                } label: {
                    Text(option)
                        .font(FWTypography.eyebrowLabel)
                        .tracking(FWTracking.metaLabel)
                        .textCase(.uppercase)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, FWSpacing.sm + 2)
                        .foregroundStyle(isActive ? FWColor.onAccent : FWColor.textDim)
                        .background(isActive ? FWColor.accent : .clear)
                        .clipShape(RoundedRectangle(cornerRadius: FWRadius.small + 1, style: .continuous))
                }
                .accessibilityAddTraits(isActive ? .isSelected : [])
            }
        }
        .padding(FWSpacing.xxs)
        .background(FWColor.surface)
        .clipShape(RoundedRectangle(cornerRadius: FWRadius.medium - 2, style: .continuous))
        .accessibilityElement(children: .contain)
    }
}
