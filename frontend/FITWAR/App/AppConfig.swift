import Foundation

/// The API base URL is never hardcoded in Swift source — it comes from the active
/// build configuration's `.xcconfig` via `Info.plist`'s `API_BASE_URL` key
/// (Architecture §15 / this phase's §8).
enum AppConfig {
    static let apiBaseURL: URL = {
        guard
            let raw = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
            let url = URL(string: raw),
            url.host != nil
        else {
            fatalError("API_BASE_URL is missing or invalid — check the active .xcconfig in App/Config/.")
        }
        #if !DEBUG
        // A non-Debug build is one that can reach a real person: TestFlight, App Store,
        // an internal staging build handed to a tester. The two ways that goes wrong are
        // shipping a build still pointed at a developer's machine, and shipping one
        // pointed at a hostname nobody ever replaced.
        //
        // Both are silent at build time and look like "the app is broken" at runtime, on
        // someone else's device. Crashing here instead means the mistake is found by
        // whoever made it, the first time they launch the build.
        let host = url.host ?? ""
        precondition(
            url.scheme == "https",
            "API_BASE_URL must be https in a non-Debug build (got \(url.scheme ?? "nil"))."
        )
        precondition(
            !host.hasSuffix(".example") && !host.hasSuffix(".example.com"),
            "API_BASE_URL is still the placeholder host '\(host)'. Set the real domain in "
                + "App/Config/Staging.xcconfig or Release.xcconfig."
        )
        precondition(
            host != "localhost" && host != "127.0.0.1" && !host.hasSuffix(".local"),
            "API_BASE_URL points at '\(host)' in a non-Debug build — that reaches only the "
                + "machine that built it."
        )
        #endif
        return url
    }()
}
