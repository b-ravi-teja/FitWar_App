import SwiftUI

/// Card elevation shadow. Source: `--shadow` custom property — dark `0 18px 44px
/// rgba(0,0,0,.55)`, light `0 18px 60px rgba(20,22,20,.14)`. SwiftUI's `.shadow()`
/// has no CSS-style offset+blur+spread triple, so this is expressed as the closest
/// `(color, radius, x, y)` equivalent.
struct FWShadowStyle {
    let color: Color
    let radius: CGFloat
    let x: CGFloat
    let y: CGFloat
}

enum FWShadow {
    static let card = FWShadowStyle(
        color: Color(light: .black.opacity(0.14), dark: .black.opacity(0.55)),
        radius: 22,
        x: 0,
        y: 9
    )
}

extension View {
    func fwCardShadow() -> some View {
        shadow(color: FWShadow.card.color, radius: FWShadow.card.radius, x: FWShadow.card.x, y: FWShadow.card.y)
    }
}
