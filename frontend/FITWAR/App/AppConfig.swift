import Foundation

/// The API base URL is never hardcoded in Swift source — it comes from the active
/// build configuration's `.xcconfig` via `Info.plist`'s `API_BASE_URL` key
/// (Architecture §15 / this phase's §8).
enum AppConfig {
    static let apiBaseURL: URL = {
        guard
            let raw = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
            let url = URL(string: raw)
        else {
            fatalError("API_BASE_URL is missing or invalid — check the active .xcconfig in App/Config/.")
        }
        return url
    }()
}
