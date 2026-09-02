@testable import FITWAR

/// In-memory stand-in for the real Keychain — Architecture §9: "protocol
/// abstractions so ViewModels can use a mock Keychain during tests."
final class MockKeychainStore: KeychainStoring, @unchecked Sendable {
    private var storage: [String: String] = [:]
    private(set) var saveCallCount = 0
    private(set) var deleteCallCount = 0

    func save(_ value: String, for key: String) throws {
        saveCallCount += 1
        storage[key] = value
    }

    func read(_ key: String) throws -> String? {
        storage[key]
    }

    func delete(_ key: String) throws {
        deleteCallCount += 1
        storage.removeValue(forKey: key)
    }
}
