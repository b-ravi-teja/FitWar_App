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
        // Straight to storage either way; the API never sees the bytes. Which shape the
        // grant takes is the server's choice, because S3 implementations disagree:
        // MinIO and S3 take a policy-signed multipart POST, R2 has no PostObject at all
        // and takes a signed PUT.
        guard let url = URL(string: grant.url) else { throw APIError.unknown("Bad upload URL.") }

        let (request, body) = grant.method == "PUT"
            ? putRequest(url: url, grant: grant, data: data)
            : multipartPostRequest(url: url, grant: grant, data: data, contentType: contentType)

        let (_, response) = try await URLSession.shared.upload(for: request, from: body)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            // 403 here is usually storage rejecting size or type — surfaced as a
            // product error, never as raw storage XML.
            throw APIError.unknown("Upload rejected by storage (\(code)).")
        }
    }

    /// The signed headers are applied verbatim: they are part of what was signed, so
    /// changing or omitting one makes storage reject the request.
    private func putRequest(
        url: URL, grant: PresignedUpload, data: Data
    ) -> (URLRequest, Data) {
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        for (key, value) in grant.headers {
            request.setValue(value, forHTTPHeaderField: key)
        }
        return (request, data)
    }

    /// The policy pins the content type and a size ceiling, so storage rejects an
    /// oversized or mistyped upload at the edge.
    private func multipartPostRequest(
        url: URL, grant: PresignedUpload, data: Data, contentType: String
    ) -> (URLRequest, Data) {
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
        return (request, body)
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
