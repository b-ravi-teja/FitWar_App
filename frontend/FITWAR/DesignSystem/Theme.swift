import SwiftUI

/// Dark/light is native SwiftUI (every `FWColor` token already resolves off the
/// environment's color scheme) — this only adds the future override Settings
/// (design spec §20.9, a later phase) will need: system default today, with a
/// persisted user choice ready for that screen to expose.
enum AppearancePreference: String, CaseIterable, Sendable {
    case system, light, dark

    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

@MainActor
@Observable
final class ThemeManager {
    var preference: AppearancePreference {
        didSet { UserDefaults.standard.set(preference.rawValue, forKey: Self.storageKey) }
    }

    private static let storageKey = "fitwar.appearance_preference"

    init() {
        let stored = UserDefaults.standard.string(forKey: Self.storageKey)
        preference = stored.flatMap(AppearancePreference.init(rawValue:)) ?? .system
    }
}
