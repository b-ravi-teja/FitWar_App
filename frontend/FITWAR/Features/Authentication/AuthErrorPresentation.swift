import Foundation

/// Shared error → copy mapping for every auth screen, so Login/Register/Password
/// Reset don't each reimplement the same switch. Backend error `code`s are the
/// contract (Architecture §12); this is the one place they're translated to copy.
enum AuthErrorPresentation {
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
            case "INVALID_CREDENTIALS": return "Incorrect email or password."
            case "ACCOUNT_DELETED": return "This account has been deleted."
            case "EMAIL_TAKEN": return "An account with that email already exists."
            case "VALIDATION_ERROR": return detail
            default: return detail
            }
        }
    }
}
