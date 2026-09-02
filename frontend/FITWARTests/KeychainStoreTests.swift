import Foundation
import Testing
@testable import FITWAR

/// Exercises the real `KeychainStore` against the simulator's actual Keychain —
/// this is the one test file that deliberately doesn't mock its subject, since a
/// mock of the Keychain wrapper wouldn't verify the wrapper itself works.
struct KeychainStoreTests {
    private func makeSUT() -> KeychainStore {
        KeychainStore(service: "com.fitwar.tests.\(UUID().uuidString)")
    }

    @Test func saveThenReadRoundTrips() throws {
        let sut = makeSUT()
        try sut.save("a-refresh-token-value", for: "key")
        #expect(try sut.read("key") == "a-refresh-token-value")
    }

    @Test func readMissingKeyReturnsNil() throws {
        let sut = makeSUT()
        #expect(try sut.read("never-saved") == nil)
    }

    @Test func saveOverwritesExistingValue() throws {
        let sut = makeSUT()
        try sut.save("first", for: "key")
        try sut.save("second", for: "key")
        #expect(try sut.read("key") == "second")
    }

    @Test func deleteRemovesValue() throws {
        let sut = makeSUT()
        try sut.save("value", for: "key")
        try sut.delete("key")
        #expect(try sut.read("key") == nil)
    }

    @Test func deletingMissingKeyDoesNotThrow() throws {
        let sut = makeSUT()
        try sut.delete("never-saved")
    }
}
