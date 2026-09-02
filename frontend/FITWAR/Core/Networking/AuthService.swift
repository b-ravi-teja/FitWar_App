import Foundation

struct AuthenticatedSession: Sendable {
    let userId: UUID
    let accessToken: String
    let refreshToken: String
    let expiresIn: Int
}

/// What `SessionManager` and auth ViewModels depend on — never `APIClient` directly.
protocol AuthServiceProtocol: Sendable {
    func register(email: String, password: String, displayName: String) async throws -> AuthenticatedSession
    func login(email: String, password: String) async throws -> AuthenticatedSession
    func refresh(refreshToken: String) async throws -> TokenResponseDTO
    func logout(refreshToken: String) async throws
    func requestPasswordReset(email: String) async throws
    func confirmPasswordReset(token: String, newPassword: String) async throws
}

struct AuthService: AuthServiceProtocol {
    let client: APIClientProtocol

    func register(email: String, password: String, displayName: String) async throws -> AuthenticatedSession {
        let body = RegisterRequestDTO(email: email, password: password, displayName: displayName)
        let response: RegisterResponseDTO = try await client.send(
            Endpoint(path: "/api/v1/auth/register", method: .post, body: Endpoint.encodedBody(body))
        )
        return AuthenticatedSession(
            userId: response.userId,
            accessToken: response.accessToken,
            refreshToken: response.refreshToken,
            expiresIn: response.expiresIn
        )
    }

    func login(email: String, password: String) async throws -> AuthenticatedSession {
        let body = LoginRequestDTO(email: email, password: password)
        let response: TokenResponseDTO = try await client.send(
            Endpoint(path: "/api/v1/auth/login", method: .post, body: Endpoint.encodedBody(body))
        )
        // /login doesn't return user_id (API_SPEC.md) — the caller (SessionManager)
        // decodes it from the access token's `sub` claim instead of a second request.
        guard let userId = JWTInspector.subject(of: response.accessToken) else {
            throw APIError.decodingFailed
        }
        return AuthenticatedSession(
            userId: userId,
            accessToken: response.accessToken,
            refreshToken: response.refreshToken,
            expiresIn: response.expiresIn
        )
    }

    func refresh(refreshToken: String) async throws -> TokenResponseDTO {
        let body = RefreshRequestDTO(refreshToken: refreshToken)
        return try await client.send(
            Endpoint(path: "/api/v1/auth/refresh", method: .post, body: Endpoint.encodedBody(body))
        )
    }

    func logout(refreshToken: String) async throws {
        let body = LogoutRequestDTO(refreshToken: refreshToken)
        try await client.sendNoContent(
            Endpoint(path: "/api/v1/auth/logout", method: .post, body: Endpoint.encodedBody(body))
        )
    }

    func requestPasswordReset(email: String) async throws {
        let body = PasswordResetRequestDTO(email: email)
        try await client.sendNoContent(
            Endpoint(path: "/api/v1/auth/password-reset/request", method: .post, body: Endpoint.encodedBody(body))
        )
    }

    func confirmPasswordReset(token: String, newPassword: String) async throws {
        let body = PasswordResetConfirmDTO(token: token, newPassword: newPassword)
        try await client.sendNoContent(
            Endpoint(path: "/api/v1/auth/password-reset/confirm", method: .post, body: Endpoint.encodedBody(body))
        )
    }
}

/// Decodes only the unsigned `sub` claim from a JWT — used purely to recover the
/// user id the `/login` response doesn't include. This is NOT signature verification
/// (the client has no business verifying its own freshly-issued token; the server
/// already did) — just base64 payload decoding.
enum JWTInspector {
    static func subject(of jwt: String) -> UUID? {
        let parts = jwt.split(separator: ".")
        guard parts.count == 3 else { return nil }
        var base64 = String(parts[1])
        base64 = base64.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 { base64.append("=") }
        guard let data = Data(base64Encoded: base64),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sub = payload["sub"] as? String
        else { return nil }
        return UUID(uuidString: sub)
    }
}
