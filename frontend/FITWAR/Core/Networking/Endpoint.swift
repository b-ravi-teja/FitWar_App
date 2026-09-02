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
        return encoder
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .fitwar
        return decoder
    }()
}
