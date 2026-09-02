import CoreGraphics

/// Spacing scale. Values reflect the recurring gaps/padding in `FITWAR.dc.html`
/// (`gap:8/10/12/14/18/20/22px`, screen padding `20-28px`, etc.), quantized to a
/// consistent 4pt-based scale rather than copying every one-off pixel value.
enum FWSpacing {
    static let xxs: CGFloat = 4
    static let xs: CGFloat = 6
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 20
    static let xxl: CGFloat = 24
    static let xxxl: CGFloat = 32

    /// Standard screen edge padding (the prototype's recurring `padding:...20px`/`24px`).
    static let screenHorizontal: CGFloat = 20
}
