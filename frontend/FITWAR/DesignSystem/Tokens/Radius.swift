import CoreGraphics

/// Corner-radius scale, matching the design spec's observed 4-tier system
/// (design spec §3: "6–8 / 12–16 / 18–22 / 99px").
enum FWRadius {
    static let small: CGFloat = 8 // icon swatches, small chips
    static let medium: CGFloat = 14 // buttons, inputs
    static let large: CGFloat = 20 // cards
    static let pill: CGFloat = 999 // progress bars, avatars, segmented tabs
}
