import Foundation
import Testing

@testable import FITWAR

/// Decoding against real server payload shapes, captured from the running backend.
struct Phase6DecodingTests {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONCoding.decoder.decode(type, from: Data(json.utf8))
    }

    @Test func decodesAPresignedUploadGrant() throws {
        let grant = try decode(PresignedUpload.self, Self.grantJSON)

        #expect(grant.fields["key"] != nil)
        #expect(grant.maxBytes == 262_144_000)
        #expect(grant.expiresInSeconds == 900)
    }

    /// A grant with no `method` is the POST shape. Servers deployed before the field
    /// existed send exactly this, and the app must keep uploading against them.
    @Test func aGrantWithoutAMethodDefaultsToPost() throws {
        let grant = try decode(PresignedUpload.self, Self.grantJSON)

        #expect(grant.method == "POST")
        #expect(grant.headers.isEmpty)
    }

    /// The Cloudflare R2 shape: no policy fields, and the signed headers the PUT must
    /// carry. R2 has no S3 PostObject, so an R2 deployment only ever issues these.
    @Test func decodesAPutGrant() throws {
        let grant = try decode(PresignedUpload.self, Self.putGrantJSON)

        #expect(grant.method == "PUT")
        #expect(grant.fields.isEmpty)
        #expect(grant.headers["Content-Type"] == "video/mp4")
    }

    @Test func decodesAProcessedAsset() throws {
        let asset = try decode(MediaAsset.self, Self.processedJSON)

        #expect(asset.status == .processed)
        #expect(asset.sizeBytes == 212)
        #expect(asset.isAvailable)
    }

    @Test func anExpiredAssetIsNotAvailable() throws {
        /// Retention deleted the object; the UI must say so rather than show a player.
        let asset = try decode(MediaAsset.self, Self.expiredJSON)

        #expect(asset.status == .expired)
        #expect(asset.playbackURL == nil)
        #expect(!asset.isAvailable)
    }

    @Test func decodesThePendingProofQueue() throws {
        let proofs = try decode([PendingProof].self, Self.queueJSON)

        #expect(proofs.count == 1)
        #expect(proofs[0].participantDisplayName == "Athlete")
        #expect(proofs[0].claimedValue == Decimal(string: "60.00"))
        #expect(proofs[0].mediaAvailable)
    }

    @Test func decodesAReviewResult() throws {
        let result = try decode(ReviewProofResult.self, Self.reviewJSON)

        #expect(result.status == .verified)
        #expect(result.xpAwarded == 50)
        #expect(result.currentStreak == 1)
        #expect(!result.alreadyResolved)
    }

    @Test func decodesAChatPageWithBothCursorParts() throws {
        let page = try decode(ChatPage.self, Self.chatJSON)

        #expect(page.items.count == 2)
        #expect(page.items[0].content == "newest")
        #expect(page.items[1].messageType == .system)
        // Both halves are needed: timestamps tie, ids don't.
        #expect(page.nextCursor != nil)
        #expect(page.nextCursorId != nil)
    }

    @Test func decodesReactionSummaries() throws {
        let page = try decode(ChatPage.self, Self.chatJSON)

        let reaction = try #require(page.items.first?.reactions.first)
        #expect(reaction.emoji == "🔥")
        #expect(reaction.count == 2)
        #expect(reaction.reactedByMe)
    }

    private static let putGrantJSON = """
    {"media_id":"aa000000-0000-0000-0000-000000000002",
     "url":"https://acct.r2.cloudflarestorage.com/fitwar-media/verification_proof/u/x.mp4?X-Amz-Signature=abc",
     "fields":{},
     "expires_in_seconds":900,"max_bytes":262144000,
     "method":"PUT","headers":{"Content-Type":"video/mp4"}}
    """

    private static let grantJSON = """
    {"media_id":"aa000000-0000-0000-0000-000000000001",
     "url":"http://localhost:9000/fitwar-media",
     "fields":{"key":"verification_proof/u/x.mp4","Content-Type":"video/mp4","policy":"eyJ"},
     "expires_in_seconds":900,"max_bytes":262144000}
    """

    private static let processedJSON = """
    {"id":"aa000000-0000-0000-0000-000000000002","status":"processed","content_type":"video/mp4",
     "size_bytes":212,"playback_url":"http://localhost:9000/signed","expires_at":null,
     "object_deleted_at":null}
    """

    private static let expiredJSON = """
    {"id":"aa000000-0000-0000-0000-000000000003","status":"expired","content_type":"video/mp4",
     "size_bytes":212,"playback_url":null,"expires_at":"2026-09-03T15:18:59.598467Z",
     "object_deleted_at":"2026-09-03T15:20:00.000000Z"}
    """

    private static let queueJSON = """
    [{"verification_record_id":"bb000000-0000-0000-0000-000000000001",
      "participant_user_id":"cc000000-0000-0000-0000-000000000001",
      "participant_display_name":"Athlete","challenge_day":"2026-09-02T00:00:00Z",
      "claimed_value":"60.00","target":"50.00","submitted_at":"2026-09-02T10:00:00.000000Z",
      "media_id":"aa000000-0000-0000-0000-000000000002","media_available":true}]
    """

    private static let reviewJSON = """
    {"verification_record_id":"bb000000-0000-0000-0000-000000000001","status":"verified",
     "reviewed_at":"2026-09-02T10:05:00.000000Z","already_resolved":false,
     "xp_awarded":50,"current_streak":1}
    """

    private static let chatJSON = """
    {"items":[
      {"id":"dd000000-0000-0000-0000-000000000001","group_id":"ee000000-0000-0000-0000-000000000001",
       "sender_id":"cc000000-0000-0000-0000-000000000001","sender_display_name":"UserA",
       "content":"newest","message_type":"text","created_at":"2026-09-02T10:10:00.000000Z",
       "reactions":[{"emoji":"🔥","count":2,"reacted_by_me":true}]},
      {"id":"dd000000-0000-0000-0000-000000000002","group_id":"ee000000-0000-0000-0000-000000000001",
       "sender_id":null,"sender_display_name":null,"content":"Athlete completed today",
       "message_type":"system","created_at":"2026-09-02T10:00:00.000000Z","reactions":[]}],
     "next_cursor":"2026-09-02T10:00:00.000000Z",
     "next_cursor_id":"dd000000-0000-0000-0000-000000000002"}
    """
}

@MainActor
struct ProofUploadTests {
    private func makeSUT(
        method: VerificationMethod = .manualProof
    ) -> (VerifyViewModel, MockChallengesService, MockVerificationService, MockMediaService) {
        let challenges = MockChallengesService()
        let verification = MockVerificationService()
        let media = MockMediaService()
        challenges.todayResult = .success(Fixture.dailyProgress())
        let sut = VerifyViewModel(
            challenge: Fixture.challengeDetail(verificationMethod: method),
            challenges: challenges,
            verification: verification,
            health: MockHealthKitService(),
            media: media
        )
        return (sut, challenges, verification, media)
    }

    @Test func aManualProofChallengeAsksForAVideoNotHealthData() async {
        let (sut, _, _, _) = makeSUT()

        await sut.load()

        guard case .awaitingProofSelection = sut.state else {
            Issue.record("expected awaitingProofSelection, got \(sut.state)")
            return
        }
    }

    @Test func uploadThenSubmitEndsInPendingReview() async {
        /// A submitted proof is never complete — a human still has to approve it.
        let (sut, _, verification, media) = makeSUT()
        verification.submitResult = .success(
            VerificationFixtures.response(dayStatus: .pending, status: .pendingReview)
        )
        await sut.load()

        await sut.submitProof(videoData: Data(count: 4096), contentType: "video/mp4")

        guard case .proofPendingReview = sut.state else {
            Issue.record("expected proofPendingReview, got \(sut.state)")
            return
        }
        #expect(media.uploadedBytes == 4096)
        #expect(media.completedIds.count == 1)
    }

    @Test func theSubmissionCarriesTheMediaReference() async {
        let (sut, _, verification, media) = makeSUT()
        let grantId = UUID()
        media.prepareResult = .success(
            PresignedUpload(
                mediaId: grantId, url: "https://s/b", fields: [:],
                expiresInSeconds: 900, maxBytes: 262_144_000
            )
        )
        verification.submitResult = .success(
            VerificationFixtures.response(dayStatus: .pending, status: .pendingReview)
        )
        await sut.load()

        await sut.submitProof(videoData: Data(count: 10), contentType: "video/mp4")

        let request = try? #require(verification.submittedRequests.first)
        #expect(request?.provider == .manualProof)
        #expect(request?.evidence.mediaId == grantId)
    }

    @Test func anOversizedVideoIsRefusedBeforeUploading() async {
        /// Checked client-side for a fast message; storage and the server enforce it too.
        let (sut, _, _, media) = makeSUT()
        media.prepareResult = .success(
            PresignedUpload(
                mediaId: UUID(), url: "https://s/b", fields: [:],
                expiresInSeconds: 900, maxBytes: 1024
            )
        )
        await sut.load()

        await sut.submitProof(videoData: Data(count: 5000), contentType: "video/mp4")

        guard case .rejected(let message) = sut.state else {
            Issue.record("expected rejected, got \(sut.state)")
            return
        }
        #expect(message.contains("too large"))
        #expect(media.uploadedBytes == nil, "nothing should have been uploaded")
    }

    @Test func anUnsupportedTypeIsRefused() async {
        let (sut, _, _, media) = makeSUT()
        await sut.load()

        await sut.submitProof(videoData: Data(count: 10), contentType: "image/gif")

        guard case .rejected = sut.state else {
            Issue.record("expected rejected, got \(sut.state)")
            return
        }
        #expect(media.uploadedBytes == nil)
    }

    @Test func anUploadFailureSurfacesAsAProductError() async {
        let (sut, _, _, media) = makeSUT()
        media.uploadError = APIError.unknown("Upload rejected by storage (403).")
        await sut.load()

        await sut.submitProof(videoData: Data(count: 10), contentType: "video/mp4")

        guard case .serverError = sut.state else {
            Issue.record("expected serverError, got \(sut.state)")
            return
        }
    }

    @Test func networkFailureDuringSubmissionIsItsOwnState() async {
        let (sut, _, verification, _) = makeSUT()
        verification.submitResult = .failure(APIError.noConnection)
        await sut.load()

        await sut.submitProof(videoData: Data(count: 10), contentType: "video/mp4")

        #expect(sut.state == .networkFailure)
    }

    @Test func cancellingThePickerReturnsToSelection() async {
        let (sut, _, _, _) = makeSUT()
        await sut.load()

        sut.proofSelectionFailed(.cancelled)

        guard case .awaitingProofSelection = sut.state else {
            Issue.record("expected awaitingProofSelection, got \(sut.state)")
            return
        }
    }

    @Test func anAlreadyCompletedDayShowsTheResolvedProof() async {
        let (sut, challenges, _, _) = makeSUT()
        challenges.todayResult = .success(Fixture.dailyProgress(status: .completed))

        await sut.load()

        guard case .proofPendingReview = sut.state else {
            Issue.record("expected a resolved state, got \(sut.state)")
            return
        }
    }

    @Test func aHealthChallengeStillUsesTheHealthPath() async {
        /// The screen branches on the challenge's declared method, not on the device.
        let (sut, _, _, _) = makeSUT(method: .appleHealth)

        await sut.load()

        guard case .readyToSync = sut.state else {
            Issue.record("expected readyToSync, got \(sut.state)")
            return
        }
    }
}

@MainActor
struct ProofReviewViewModelTests {
    private func makeSUT() -> (ProofReviewViewModel, MockMediaService) {
        let media = MockMediaService()
        return (ProofReviewViewModel(challengeId: UUID(), media: media), media)
    }

    @Test func loadsTheQueue() async {
        let (sut, media) = makeSUT()
        media.pendingResult = .success([MediaFixtures.pendingProof()])

        await sut.load()

        #expect(sut.state.value?.count == 1)
    }

    @Test func anUnauthorizedReviewerSeesForbiddenNotAnEmptyQueue() async {
        /// Server-enforced: hiding the button is not the control.
        let (sut, media) = makeSUT()
        media.pendingResult = .failure(
            APIError.server(status: 403, code: "NOT_A_REVIEWER", detail: "nope")
        )

        await sut.load()

        guard case .serverError = sut.state else {
            Issue.record("expected serverError, got \(sut.state)")
            return
        }
    }

    @Test func approvingCallsTheServerAndRefreshes() async {
        let (sut, media) = makeSUT()
        let proof = MediaFixtures.pendingProof()
        media.pendingResult = .success([proof])
        media.reviewResult = .success(
            ReviewProofResult(
                verificationRecordId: proof.verificationRecordId, status: .verified,
                reviewedAt: Date(), alreadyResolved: false, xpAwarded: 50, currentStreak: 1
            )
        )
        await sut.load()

        await sut.review(proof, approve: true)

        #expect(media.reviewCalls.map(\.1) == [true])
    }

    @Test func rejectingPassesApproveFalse() async {
        let (sut, media) = makeSUT()
        let proof = MediaFixtures.pendingProof()
        media.pendingResult = .success([proof])
        media.reviewResult = .success(
            ReviewProofResult(
                verificationRecordId: proof.verificationRecordId, status: .rejected,
                reviewedAt: Date(), alreadyResolved: false, xpAwarded: nil, currentStreak: nil
            )
        )
        await sut.load()

        await sut.review(proof, approve: false, note: "not a rep")

        #expect(media.reviewCalls.map(\.1) == [false])
    }

    @Test func noPlaybackURLOnceTheVideoExpired() async {
        /// No broken player: the reviewer is told it is gone.
        let (sut, media) = makeSUT()
        media.proofMediaResult = .success(
            MediaFixtures.asset(status: .expired, playbackURL: nil, deletedAt: Date())
        )

        let url = await sut.playbackURL(for: MediaFixtures.pendingProof(available: false))

        #expect(url == nil)
    }
}
