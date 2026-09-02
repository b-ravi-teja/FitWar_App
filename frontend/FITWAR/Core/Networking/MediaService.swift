import Foundation

/// Media upload and proof review.
///
/// The upload itself goes **directly to object storage**, not through the API — that is
/// what keeps large videos off the app server. The client receives a single-object,
/// short-lived grant and never any bucket credentials.
protocol MediaServiceProtocol: Sendable {
    func prepareUpload(contentType: String) async throws -> PresignedUpload
    func uploadData(_ data: Data, to grant: PresignedUpload, contentType: String) async throws
    func completeUpload(mediaId: UUID) async throws -> MediaAsset
    func fetchPendingProofs(challengeId: UUID) async throws -> [PendingProof]
    func fetchProofMedia(challengeId: UUID, recordId: UUID) async throws -> MediaAsset
    func reviewProof(
        challengeId: UUID, recordId: UUID, approve: Bool, note: String?
    ) async throws -> ReviewProofResult
}

struct MediaService: MediaServiceProtocol {
    let client: APIClientProtocol

    func prepareUpload(contentType: String) async throws -> PresignedUpload {
        try await client.send(
            Endpoint(
                path: "/api/v1/media/upload-url",
                method: .post,
                body: Endpoint.encodedBody(["content_type": contentType]),
                requiresAuth: true
            )
        )
    }

    func uploadData(_ data: Data, to grant: PresignedUpload, contentType: String) async throws {
        // A multipart POST to storage, carrying the signed policy fields verbatim. The
        // policy pins the content type and a size ceiling, so storage rejects an
        // oversized or mistyped upload without the API ever seeing the bytes.
        guard let url = URL(string: grant.url) else { throw APIError.unknown("Bad upload URL.") }
        let boundary = "fitwar-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        func append(_ string: String) { body.append(Data(string.utf8)) }
        for (key, value) in grant.fields {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"proof.mp4\"\r\n")
        append("Content-Type: \(contentType)\r\n\r\n")
        body.append(data)
        append("\r\n--\(boundary)--\r\n")

        let (_, response) = try await URLSession.shared.upload(for: request, from: body)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            // 403 here is usually the policy rejecting size or type — surfaced as a
            // product error, never as raw storage XML.
            throw APIError.unknown("Upload rejected by storage (\(code)).")
        }
    }

    func completeUpload(mediaId: UUID) async throws -> MediaAsset {
        try await client.send(
            Endpoint(
                path: "/api/v1/media/\(mediaId.uuidString)/complete",
                method: .post,
                requiresAuth: true
            )
        )
    }

    func fetchPendingProofs(challengeId: UUID) async throws -> [PendingProof] {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/proofs/pending",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func fetchProofMedia(challengeId: UUID, recordId: UUID) async throws -> MediaAsset {
        try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/proofs/\(recordId.uuidString)/media",
                method: .get,
                requiresAuth: true
            )
        )
    }

    func reviewProof(
        challengeId: UUID, recordId: UUID, approve: Bool, note: String?
    ) async throws -> ReviewProofResult {
        struct Body: Encodable { let approve: Bool; let note: String? }
        return try await client.send(
            Endpoint(
                path: "/api/v1/challenges/\(challengeId.uuidString)/proofs/\(recordId.uuidString)/review",
                method: .post,
                body: Endpoint.encodedBody(Body(approve: approve, note: note)),
                requiresAuth: true
            )
        )
    }
}
