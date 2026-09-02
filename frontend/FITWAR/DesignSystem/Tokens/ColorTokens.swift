import SwiftUI

/// Dynamic light/dark color, resolved by the system trait collection — the SwiftUI
/// equivalent of the prototype's `[data-fw]` / `[data-fw="light"]` CSS variable swap.
extension Color {
    init(light: Color, dark: Color) {
        self.init(
            UIColor { traits in
                traits.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light)
            }
        )
    }
}

/// FITWAR color tokens. Values are taken directly from `FITWAR.dc.html`'s `[data-fw]`
/// CSS custom properties — the dark palette is the prototype's default block, the light
/// palette is `[data-fw="light"]`. Semantic accents (red/orange/blue/gold/purple) are
/// NOT redefined for light mode in the source design, so they're shared across both
/// themes here too, matching that choice exactly rather than inventing new values.
enum FWColor {
    // MARK: Dark palette (source: `[data-fw]` block)

    private enum Dark {
        static let background = Color(red: 0x08 / 255, green: 0x09 / 255, blue: 0x0A / 255)
        static let surface = Color(red: 0x12 / 255, green: 0x14 / 255, blue: 0x15 / 255)
        static let surface2 = Color(red: 0x1A / 255, green: 0x1D / 255, blue: 0x1F / 255)
        static let line = Color(.sRGB, red: 1, green: 1, blue: 1, opacity: 0.09)
        static let line2 = Color(.sRGB, red: 1, green: 1, blue: 1, opacity: 0.16)
        static let textPrimary = Color(red: 0xF2 / 255, green: 0xF4 / 255, blue: 0xF3 / 255)
        static let textDim = Color(.sRGB, red: 0xF2 / 255, green: 0xF4 / 255, blue: 0xF3 / 255, opacity: 0.52)
        static let textDim2 = Color(.sRGB, red: 0xF2 / 255, green: 0xF4 / 255, blue: 0xF3 / 255, opacity: 0.34)
        static let onAccent = Color(red: 0x0A / 255, green: 0x0F / 255, blue: 0x04 / 255)
        static let accent = Color(red: 0xBA / 255, green: 0xF6 / 255, blue: 0x28 / 255) // oklch(.90 .22 126)
    }

    // MARK: Light palette (source: `[data-fw="light"]` block)

    private enum Light {
        static let background = Color(red: 0xF5 / 255, green: 0xF5 / 255, blue: 0xF2 / 255)
        static let surface = Color(red: 1, green: 1, blue: 1)
        static let surface2 = Color(red: 0xEC / 255, green: 0xEC / 255, blue: 0xEA / 255)
        static let line = Color(.sRGB, red: 0x0A / 255, green: 0x0C / 255, blue: 0x0B / 255, opacity: 0.09)
        static let line2 = Color(.sRGB, red: 0x0A / 255, green: 0x0C / 255, blue: 0x0B / 255, opacity: 0.16)
        static let textPrimary = Color(red: 0x0D / 255, green: 0x0F / 255, blue: 0x10 / 255)
        static let textDim = Color(.sRGB, red: 0x0D / 255, green: 0x0F / 255, blue: 0x10 / 255, opacity: 0.55)
        static let textDim2 = Color(.sRGB, red: 0x0D / 255, green: 0x0F / 255, blue: 0x10 / 255, opacity: 0.35)
        static let onAccent = Color(red: 0x08 / 255, green: 0x11 / 255, blue: 0x0A / 255)
        static let accent = Color(red: 0x98 / 255, green: 0xD4 / 255, blue: 0x23 / 255) // oklch(.80 .20 128)
    }

    // MARK: Semantic tokens (theme-adaptive)

    static let background = Color(light: Light.background, dark: Dark.background)
    static let surface = Color(light: Light.surface, dark: Dark.surface)
    static let surface2 = Color(light: Light.surface2, dark: Dark.surface2)
    static let line = Color(light: Light.line, dark: Dark.line)
    static let line2 = Color(light: Light.line2, dark: Dark.line2)
    static let textPrimary = Color(light: Light.textPrimary, dark: Dark.textPrimary)
    static let textDim = Color(light: Light.textDim, dark: Dark.textDim)
    static let textDim2 = Color(light: Light.textDim2, dark: Dark.textDim2)
    static let accent = Color(light: Light.accent, dark: Dark.accent)
    static let onAccent = Color(light: Light.onAccent, dark: Dark.onAccent)

    // MARK: Fixed semantic accents (shared across both themes, matching the source design)

    static let red = Color(red: 0xF8 / 255, green: 0x4B / 255, blue: 0x4B / 255) // oklch(.66 .21 25)
    static let orange = Color(red: 0xFF / 255, green: 0x9B / 255, blue: 0x24 / 255) // oklch(.78 .17 62)
    static let blue = Color(red: 0x4B / 255, green: 0xAE / 255, blue: 0xED / 255) // oklch(.72 .13 240)
    static let gold = Color(red: 0xF6 / 255, green: 0xC3 / 255, blue: 0x30 / 255) // oklch(.84 .16 88)
    static let purple = Color(red: 0xAE / 255, green: 0x84 / 255, blue: 0xF2 / 255) // oklch(.70 .16 300)
}
