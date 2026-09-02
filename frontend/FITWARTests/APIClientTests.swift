import Foundation
import Testing
@testable import FITWAR

/// Intercepts every request at the `URLProtocol` level — the standard way to test
/// real `URLSession`-based code without touching the network (this phase's §20).
final class MockURLProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

struct APIClientTests {
    private func makeSUT() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        return APIClient(baseURL: URL(string: "https://api.fitwar.test")!, session: URLSession(configuration: config))
    }

    private struct Sample: Decodable, Equatable {
        let value: String
    }

    @Test func decodesSuccessfulJSONResponseWithSnakeCaseKeys() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"value":"hello"}"#.utf8))
        }
        let sut = makeSUT()

        let result: Sample = try await sut.send(Endpoint(path: "/thing", method: .get))

        #expect(result == Sample(value: "hello"))
    }

    @Test func mapsProblemDetailErrorResponseToServerError() async {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 409, httpVersion: nil, headerFields: nil)!
            let body = #"{"type":"email_taken","title":"Email Taken","status":409,"detail":"already exists","code":"EMAIL_TAKEN"}"#
            return (response, Data(body.utf8))
        }
        let sut = makeSUT()

        await #expect(throws: APIError.server(status: 409, code: "EMAIL_TAKEN", detail: "already exists")) {
            let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .post))
        }
    }

    @Test func mapsMalformedJSONToDecodingFailed() async {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data("not json".utf8))
        }
        let sut = makeSUT()

        await #expect(throws: APIError.decodingFailed) {
            let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .get))
        }
    }

    @Test func mapsConnectionLostToNoConnection() async {
        MockURLProtocol.handler = { _ in throw URLError(.notConnectedToInternet) }
        let sut = makeSUT()

        await #expect(throws: APIError.noConnection) {
            let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .get))
        }
    }

    @Test func mapsTimeoutToTimeout() async {
        MockURLProtocol.handler = { _ in throw URLError(.timedOut) }
        let sut = makeSUT()

        await #expect(throws: APIError.timeout) {
            let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .get))
        }
    }

    @Test func attachesBearerTokenWhenEndpointRequiresAuth() async throws {
        var capturedAuthHeader: String?
        MockURLProtocol.handler = { request in
            capturedAuthHeader = request.value(forHTTPHeaderField: "Authorization")
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"value":"ok"}"#.utf8))
        }
        let sut = makeSUT()
        sut.accessTokenProvider = { "test-access-token" }

        let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .get, requiresAuth: true))

        #expect(capturedAuthHeader == "Bearer test-access-token")
    }

    @Test func doesNotAttachAuthHeaderWhenEndpointDoesNotRequireIt() async throws {
        var capturedAuthHeader: String?
        MockURLProtocol.handler = { request in
            capturedAuthHeader = request.value(forHTTPHeaderField: "Authorization")
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"value":"ok"}"#.utf8))
        }
        let sut = makeSUT()
        sut.accessTokenProvider = { "should-not-be-used" }

        let _: Sample = try await sut.send(Endpoint(path: "/thing", method: .get, requiresAuth: false))

        #expect(capturedAuthHeader == nil)
    }
}
