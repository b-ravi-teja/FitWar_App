import Foundation

/// Mirrors the backend's Problem Details envelope (`{type, title, status, detail, code}`,
/// Architecture §12) exactly — `code` is the field ViewModels are expected to switch on.
struct APIProblemDetail: Decodable, Sendable {
    let type: String
    let title: String
    let status: Int
    let detail: String
    let code: String
}

/// Typed errors surfaced to ViewModels. Every networking failure mode the design spec's
/// generic states (§20.10) need to distinguish gets its own case, rather than leaking
/// `URLError`/`DecodingError` up past this layer.
enum APIError: Error, Equatable, Sendable {
    case noConnection
    case timeout
    case decodingFailed
    case server(status: Int, code: String, detail: String)
    case unknown(String)

    var isUnauthorized: Bool {
        if case .server(let status, _, _) = self { return status == 401 }
        return false
    }

    var problemCode: String? {
        if case .server(_, let code, _) = self { return code }
        return nil
    }

    /// User-facing fallback message when a screen doesn't special-case the error.
    var displayMessage: String {
        switch self {
        case .noConnection: "No internet connection."
        case .timeout: "The request timed out."
        case .decodingFailed: "Something went wrong reading the server's response."
        case .server(_, _, let detail): detail
        case .unknown: "Something went wrong."
        }
    }
}
