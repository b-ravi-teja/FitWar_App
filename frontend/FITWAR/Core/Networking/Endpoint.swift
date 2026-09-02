import Foundation

enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case patch = "PATCH"
    case delete = "DELETE"
}

/// A single API call's shape. Feature services build these; only `APIClient` ever
/// turns one into a real `URLRequest` — views and view models never touch `URLSession`.
struct Endpoint: Sendable {
    let path: String
    let method: HTTPMethod
    var query: [String: String] = [:]
    var body: Data? = nil
    var requiresAuth: Bool = false

    static func encodedBody(_ value: some Encodable) -> Data? {
        try? JSONCoding.encoder.encode(value)
    }
}

enum JSONCoding {
    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        // Dates must go out as ISO-8601 with an explicit offset. The default
        // (`.deferredToDate`) writes a bare Double of seconds since Apple's 2001
        // reference date, which the server reads as a Unix timestamp — landing the
        // value in 1995 and failing validation for reasons that look nothing like the
        // cause. Verification evidence is the first payload to carry a Date, so this
        // is the first request that would have hit it.
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .fitwar
        return decoder
    }()
}
