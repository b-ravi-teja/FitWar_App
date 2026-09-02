import Foundation

// Mirrors backend/app/schemas/auth.py exactly (API_SPEC.md — Auth).

struct RegisterRequestDTO: Encodable {
    let email: String
    let password: String
    let displayName: String
}

struct LoginRequestDTO: Encodable {
    let email: String
    let password: String
}

struct RefreshRequestDTO: Encodable {
    let refreshToken: String
}

struct LogoutRequestDTO: Encodable {
    let refreshToken: String
}

struct PasswordResetRequestDTO: Encodable {
    let email: String
}

struct PasswordResetConfirmDTO: Encodable {
    let token: String
    let newPassword: String
}

struct TokenResponseDTO: Decodable {
    let accessToken: String
    let refreshToken: String
    let expiresIn: Int
}

struct RegisterResponseDTO: Decodable {
    let userId: UUID
    let accessToken: String
    let refreshToken: String
    let expiresIn: Int
}
