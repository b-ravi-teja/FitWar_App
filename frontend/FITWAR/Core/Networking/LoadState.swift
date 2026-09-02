import Foundation

/// One load state for every screen that fetches, so each ViewModel doesn't re-declare
/// the same five cases. Maps directly onto the reusable state components the design
/// spec added in §20.10 (Loading / Empty / Network error / Unauthorized / Server error).
enum LoadState<Value: Equatable>: Equatable {
    case loading
    case loaded(Value)
    case networkError
    case serverError(String)
    case unauthorized

    var value: Value? {
        if case .loaded(let value) = self { return value }
        return nil
    }

    /// Classifies a thrown error into the right state. Centralized because getting this
    /// wrong (showing "no connection" for a 500, or a generic failure for a 401 that
    /// should force logout) is the kind of bug that only surfaces at the worst moment.
    static func from(_ error: Error) -> LoadState<Value> {
        guard let apiError = error as? APIError else { return .serverError("Something went wrong.") }
        switch apiError {
        case .noConnection, .timeout:
            return .networkError
        case .server(let status, _, _) where status == 401:
            return .unauthorized
        case .server, .decodingFailed, .unknown:
            return .serverError(DomainErrorPresentation.message(for: apiError))
        }
    }
}

/// Backend error `code` → user-facing copy for the Groups/Challenges domain.
///
/// `code` is the stable contract (Architecture §12); `detail` is explicitly not
/// guaranteed-stable copy, so anything the user is likely to hit gets its own line here
/// rather than leaking a server sentence.
enum DomainErrorPresentation {
    static func message(for error: Error) -> String {
        guard let apiError = error as? APIError else { return "Something went wrong. Try again." }

        switch apiError {
        case .noConnection:
            return "No internet connection. Check your network and try again."
        case .timeout:
            return "The request timed out. Try again."
        case .decodingFailed, .unknown:
            return "Something went wrong. Try again."
        case .server(_, let code, let detail):
            switch code {
            case "INVALID_CODE":
                return "That invite code doesn't match a squad. Check it and try again."
            case "ALREADY_MEMBER":
                return "You're already in this squad."
            case "MEMBER_REMOVED":
                return "An admin removed you from this squad."
            case "OWNER_CANNOT_LEAVE":
                return "You own this squad, so you can't leave it."
            case "NOT_A_MEMBER":
                return "You're not a member of this squad."
            case "INVALID_TIMEZONE":
                return "That timezone isn't recognised. Pick another."
            case "ALREADY_JOINED":
                return "You're already in this challenge."
            case "PARTICIPANT_LIMIT_REACHED":
                return "This challenge is full."
            case "CANNOT_REJOIN":
                return "You can't re-enter a challenge you already left or finished."
            case "CHALLENGE_ALREADY_ENDED":
                return "This challenge has already ended."
            case "CHALLENGE_ALREADY_ACTIVE":
                return "This challenge has already started and can't be changed."
            case "CHALLENGE_NOT_ACTIVE":
                return "This challenge isn't running right now."
            case "CHALLENGE_NOT_FOUND":
                return "That challenge no longer exists."
            case "GROUP_NOT_FOUND":
                return "That squad no longer exists."
            case "NOT_A_PARTICIPANT":
                return "You haven't joined this challenge."
            case "FORBIDDEN", "CANNOT_MODIFY_OWNER":
                return "You don't have permission to do that."
            case "INVALID_STATE_TRANSITION":
                return "That isn't possible from the challenge's current state."
            case "VALIDATION_ERROR":
                return detail
            default:
                return detail
            }
        }
    }
}
