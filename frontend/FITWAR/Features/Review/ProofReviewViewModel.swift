import Foundation
import Observation

@MainActor
@Observable
final class ProofReviewViewModel {
    private(set) var state: LoadState<[PendingProof]> = .loading
    private(set) var reviewingId: UUID?
    private(set) var lastError: String?

    private let challengeId: UUID
    private let media: MediaServiceProtocol

    init(challengeId: UUID, media: MediaServiceProtocol) {
        self.challengeId = challengeId
        self.media = media
    }

    func load() async {
        state = .loading
        do {
            state = .loaded(try await media.fetchPendingProofs(challengeId: challengeId))
        } catch {
            state = LoadState.from(error)
        }
    }

    /// A short-lived signed URL, fetched only when the reviewer opens a proof — proof is
    /// private, so playback access is granted per view rather than listed in the queue.
    func playbackURL(for proof: PendingProof) async -> URL? {
        guard let asset = try? await media.fetchProofMedia(
            challengeId: challengeId, recordId: proof.verificationRecordId
        ) else { return nil }
        guard asset.isAvailable, let raw = asset.playbackURL else { return nil }
        return URL(string: raw)
    }

    func review(_ proof: PendingProof, approve: Bool, note: String? = nil) async {
        guard reviewingId == nil else { return }
        reviewingId = proof.verificationRecordId
        lastError = nil
        defer { reviewingId = nil }
        do {
            _ = try await media.reviewProof(
                challengeId: challengeId,
                recordId: proof.verificationRecordId,
                approve: approve,
                note: note
            )
            // Re-read the queue: the server decides what is still pending.
            await load()
        } catch {
            lastError = DomainErrorPresentation.message(for: error)
        }
    }
}
