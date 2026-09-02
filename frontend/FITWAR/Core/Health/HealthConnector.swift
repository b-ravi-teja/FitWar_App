import Foundation

enum HealthConnectionPermissionState: Sendable, Equatable {
    case notDetermined
    case connected
    case denied
}

enum HealthProviderKind: Sendable, Equatable {
    case appleHealth
    case healthConnect
}

/// Extension point for the real HealthKit integration, which belongs to the later
/// Verification phase (§15) — Phase 2 only builds this shape and the onboarding UI
/// that will eventually call it. `UnimplementedHealthConnector` below is the Phase 2
/// stand-in: it makes no HealthKit calls and reports no fake success, so nothing here
/// pretends to have connected anything it hasn't.
protocol HealthConnector: Sendable {
    func requestConnection(for provider: HealthProviderKind) async -> HealthConnectionPermissionState
}

/// Matches `FITWAR.dc.html` exactly: both the Apple Health and Health Connect
/// buttons call the same "continue" handler in the prototype — neither simulates an
/// actual connection. Health Connect specifically is Android-only and is never
/// implemented on iOS (§15) — this connector doesn't fake it either.
struct UnimplementedHealthConnector: HealthConnector {
    func requestConnection(for provider: HealthProviderKind) async -> HealthConnectionPermissionState {
        .notDetermined
    }
}
