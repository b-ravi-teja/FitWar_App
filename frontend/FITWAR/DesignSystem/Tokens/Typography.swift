import SwiftUI

/// Font-family primitives. Archivo is the display/UI face; JetBrains Mono carries
/// every numeric/meta/label role — exactly the pairing `FITWAR.dc.html` uses
/// (`font-family: Archivo,system-ui,sans-serif` / `'JetBrains Mono',monospace`).
///
/// Both use `Font.custom(_:size:relativeTo:)` so Dynamic Type scaling applies
/// (Accessibility §23) instead of a fixed point size.
enum FWFontFamily {
    enum ArchivoWeight {
        case regular, medium, semibold, bold, extrabold

        var postscriptName: String {
            switch self {
            case .regular: "Archivo-Regular"
            case .medium: "Archivo-Medium"
            case .semibold: "Archivo-SemiBold"
            case .bold: "Archivo-Bold"
            case .extrabold: "Archivo-ExtraBold"
            }
        }
    }

    enum MonoWeight {
        case regular, medium, bold

        var postscriptName: String {
            switch self {
            case .regular: "JetBrainsMono-Regular"
            case .medium: "JetBrainsMono-Medium"
            case .bold: "JetBrainsMono-Bold"
            }
        }
    }

    static func archivo(_ size: CGFloat, _ weight: ArchivoWeight, relativeTo style: Font.TextStyle = .body) -> Font {
        .custom(weight.postscriptName, size: size, relativeTo: style)
    }

    static func mono(_ size: CGFloat, _ weight: MonoWeight, relativeTo style: Font.TextStyle = .caption) -> Font {
        .custom(weight.postscriptName, size: size, relativeTo: style)
    }
}

/// Named type-scale roles, so views reach for `FWTypography.title` instead of
/// scattering raw `.custom(...)` calls (Architecture: "centralized tokens... do not
/// scatter magic numbers"). Sizes/weights are taken from the recurring patterns in
/// `FITWAR.dc.html`; screens with a genuinely one-off huge number (the 84pt live step
/// counter, the 54pt/62pt hero stats) use `FWFontFamily.archivo(_:.extrabold)` directly
/// with that literal size, since those are intentionally singular, not reusable roles.
enum FWTypography {
    // Archivo — display/UI
    static let heroHeadline = FWFontFamily.archivo(44, .extrabold, relativeTo: .largeTitle)
    static let displayLarge = FWFontFamily.archivo(34, .extrabold, relativeTo: .largeTitle)
    static let displayMedium = FWFontFamily.archivo(30, .extrabold, relativeTo: .title)
    static let titleLarge = FWFontFamily.archivo(24, .extrabold, relativeTo: .title2)
    static let titleMedium = FWFontFamily.archivo(21, .extrabold, relativeTo: .title3)
    static let titleSmall = FWFontFamily.archivo(17, .bold, relativeTo: .headline)
    static let buttonLabel = FWFontFamily.archivo(14, .bold, relativeTo: .headline)
    static let body = FWFontFamily.archivo(16, .regular, relativeTo: .body)
    static let bodyMedium = FWFontFamily.archivo(14, .medium, relativeTo: .subheadline)
    static let bodySmall = FWFontFamily.archivo(13, .regular, relativeTo: .footnote)
    static let caption = FWFontFamily.archivo(12, .semibold, relativeTo: .caption)

    // JetBrains Mono — numeric/meta
    static let eyebrowLabel = FWFontFamily.mono(10, .medium, relativeTo: .caption2) // tracked, uppercase
    static let metaLabel = FWFontFamily.mono(9, .medium, relativeTo: .caption2)
    static let numericSmall = FWFontFamily.mono(11, .bold, relativeTo: .footnote)
    static let numericMedium = FWFontFamily.mono(14, .bold, relativeTo: .subheadline)
    static let numericLarge = FWFontFamily.mono(18, .bold, relativeTo: .title3)
    static let numericXL = FWFontFamily.mono(24, .bold, relativeTo: .title)
}

/// The eyebrow-label letter-spacing the design uses everywhere (`letter-spacing:.16em`
/// to `.24em` on tracked uppercase JetBrains Mono labels). SwiftUI has no CSS-style
/// `em` tracking, so this is expressed as a fixed-point `.tracking()` value tuned to
/// look equivalent at the token's actual point size.
enum FWTracking {
    static let eyebrow: CGFloat = 1.6
    static let metaLabel: CGFloat = 1.2
}
