import SwiftUI

/// Circular avatar placeholder. The prototype never renders an actual photo — every
/// avatar is a bordered color swatch — so Phase 2 matches that exactly; real image
/// loading is a later-phase concern (Media phase).
struct AvatarView: View {
    var size: CGFloat = 38
    var initials: String? = nil

    var body: some View {
        Circle()
            .fill(FWColor.surface2)
            .overlay(Circle().strokeBorder(FWColor.line))
            .overlay {
                if let initials, !initials.isEmpty {
                    Text(initials)
                        .font(.system(size: size * 0.38, weight: .semibold, design: .rounded))
                        .foregroundStyle(FWColor.textDim)
                }
            }
            .frame(width: size, height: size)
    }
}

/// Overlapping avatar stack (Group header member preview).
struct AvatarStack: View {
    let count: Int
    var size: CGFloat = 28
    var overlap: CGFloat = 9

    var body: some View {
        HStack(spacing: -overlap) {
            ForEach(0..<count, id: \.self) { _ in
                AvatarView(size: size)
                    .overlay(Circle().strokeBorder(FWColor.background, lineWidth: 2))
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(count) members")
    }
}
