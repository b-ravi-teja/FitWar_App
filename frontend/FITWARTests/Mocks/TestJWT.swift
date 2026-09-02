import Foundation

/// Builds a JWT-shaped string with a real `sub` claim so `JWTInspector.subject(of:)`
/// can decode it in tests — the signature is garbage, which is fine: the client
/// never verifies its own token's signature (the server already did), it only reads
/// the payload (see `JWTInspector`'s doc comment).
enum TestJWT {
    static func make(subject: UUID) -> String {
        let header = base64URL(["alg": "HS256", "typ": "JWT"])
        let payload = base64URL(["sub": subject.uuidString, "type": "access"])
        return "\(header).\(payload).fake-signature"
    }

    private static func base64URL(_ dict: [String: String]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: dict)
        return data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
