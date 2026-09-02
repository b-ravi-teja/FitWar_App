import Foundation
import Security

/// What `SessionManager` depends on — a mock conforms to this in tests, never
/// touching the real Keychain (Architecture: "Keychain... protocol abstractions so
/// ViewModels can use a mock during tests").
protocol KeychainStoring: Sendable {
    func save(_ value: String, for key: String) throws
    func read(_ key: String) throws -> String?
    func delete(_ key: String) throws
}

enum KeychainError: Error, Equatable {
    case unhandled(OSStatus)
    case unexpectedData
}

/// Stores only the refresh token (Architecture §9: the access token stays in memory
/// only, never persisted). `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` matches
/// the frozen architecture exactly — readable only after the device's first unlock
/// post-boot, and never included in a device backup/migration to another device.
final class KeychainStore: KeychainStoring {
    private let service: String

    init(service: String = Bundle.main.bundleIdentifier ?? "com.fitwar.app") {
        self.service = service
    }

    func save(_ value: String, for key: String) throws {
        let data = Data(value.utf8)
        var query = baseQuery(for: key)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

        let status = SecItemAdd(query as CFDictionary, nil)
        if status == errSecDuplicateItem {
            let attributesToUpdate: [String: Any] = [kSecValueData as String: data]
            let updateStatus = SecItemUpdate(baseQuery(for: key) as CFDictionary, attributesToUpdate as CFDictionary)
            guard updateStatus == errSecSuccess else { throw KeychainError.unhandled(updateStatus) }
            return
        }
        guard status == errSecSuccess else { throw KeychainError.unhandled(status) }
    }

    func read(_ key: String) throws -> String? {
        var query = baseQuery(for: key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError.unhandled(status) }
        guard let data = result as? Data, let string = String(data: data, encoding: .utf8) else {
            throw KeychainError.unexpectedData
        }
        return string
    }

    func delete(_ key: String) throws {
        let status = SecItemDelete(baseQuery(for: key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.unhandled(status)
        }
    }

    private func baseQuery(for key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
    }
}

enum KeychainKey {
    static let refreshToken = "fitwar.refresh_token"
}
