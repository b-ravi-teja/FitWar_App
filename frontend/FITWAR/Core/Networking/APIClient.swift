import Foundation

/// What feature services depend on — never the concrete `APIClient` — so unit tests
/// can substitute a mock without touching `URLSession` (Architecture: "protocols
/// where mocking/testing is useful").
protocol APIClientProtocol: Sendable {
    func send<T: Decodable>(_ endpoint: Endpoint) async throws -> T
    func sendNoContent(_ endpoint: Endpoint) async throws
}

/// Thin, testable wrapper over `URLSession`. Decodes JSON, maps HTTP/transport
/// failures to typed `APIError`, and attaches a bearer token when the endpoint
/// requires one. Does NOT handle 401-triggered refresh-and-retry itself — that's
/// `SessionManager`'s job (`authorizedRequest(_:)`), so this stays a simple,
/// single-responsibility HTTP layer.
final class APIClient: APIClientProtocol, @unchecked Sendable {
    private let baseURL: URL
    private let session: URLSession

    /// Supplied by `SessionManager` after construction — kept as a closure rather
    /// than a hard dependency so `APIClient` never needs to import session state.
    /// Async, deliberately: the token lives on a `@MainActor` type, and a synchronous
    /// closure reading it would need `MainActor.assumeIsolated`, which crashes if
    /// this is ever invoked from a non-main-actor context. Awaiting it costs nothing
    /// measurable and can never crash regardless of caller.
    var accessTokenProvider: (@Sendable () async -> String?)?

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    func send<T: Decodable>(_ endpoint: Endpoint) async throws -> T {
        let (data, _) = try await perform(endpoint)
        do {
            return try JSONCoding.decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingFailed
        }
    }

    func sendNoContent(_ endpoint: Endpoint) async throws {
        _ = try await perform(endpoint)
    }

    private func url(for endpoint: Endpoint) throws -> URL {
        let base = baseURL.appendingPathComponent(endpoint.path)
        guard !endpoint.query.isEmpty else { return base }
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw APIError.unknown("Could not build a request URL.")
        }
        // Sorted so a given endpoint always produces the same URL — otherwise dictionary
        // ordering makes requests non-deterministic and awkward to assert against in tests.
        components.queryItems = endpoint.query
            .sorted { $0.key < $1.key }
            .map { URLQueryItem(name: $0.key, value: $0.value) }
        guard let composed = components.url else {
            throw APIError.unknown("Could not build a request URL.")
        }
        return composed
    }

    private func perform(_ endpoint: Endpoint) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: try url(for: endpoint))
        request.httpMethod = endpoint.method.rawValue
        request.httpBody = endpoint.body
        if endpoint.body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if endpoint.requiresAuth, let token = await accessTokenProvider?() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost, .cannotFindHost:
                throw APIError.noConnection
            case .timedOut:
                throw APIError.timeout
            default:
                throw APIError.unknown(error.localizedDescription)
            }
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.unknown("Non-HTTP response")
        }

        guard (200..<300).contains(http.statusCode) else {
            if let problem = try? JSONCoding.decoder.decode(APIProblemDetail.self, from: data) {
                throw APIError.server(status: problem.status, code: problem.code, detail: problem.detail)
            }
            throw APIError.server(status: http.statusCode, code: "UNKNOWN", detail: "Request failed.")
        }

        return (data, http)
    }
}
