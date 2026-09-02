import Foundation

/// Decodes a `Decimal` that the backend sends as a JSON **string**.
///
/// Pydantic serializes `Decimal` as `"10000.00"`, not `10000.00` — the right choice on
/// the server, since a JSON number would round-trip through a binary float and lose
/// exactness on money-like values. Swift's built-in `Decimal: Decodable` only accepts a
/// JSON number, so every `Decimal` field on an API DTO needs this wrapper.
///
/// A number is accepted too, so the client doesn't break if a field is ever emitted
/// unquoted.
@propertyWrapper
struct APIDecimal: Codable, Sendable, Equatable {
    var wrappedValue: Decimal

    init(wrappedValue: Decimal) {
        self.wrappedValue = wrappedValue
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let string = try? container.decode(String.self), let value = Decimal(string: string) {
            wrappedValue = value
            return
        }
        wrappedValue = try container.decode(Decimal.self)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        // Sent back as a string too, matching what the server accepts and emits.
        try container.encode("\(wrappedValue)")
    }
}

extension JSONDecoder.DateDecodingStrategy {
    /// The backend emits three shapes across the API: timestamps with fractional
    /// seconds (`2026-09-02T06:46:53.300223Z` — Postgres microsecond precision),
    /// timestamps without them, and bare calendar days (`2026-09-02`, e.g.
    /// `DailyChallengeProgress.challenge_day`).
    ///
    /// `.iso8601` handles only the middle case, so a single strategy that tries all
    /// three is what keeps every DTO decodable.
    static let fitwar = JSONDecoder.DateDecodingStrategy.custom { decoder in
        let raw = try decoder.singleValueContainer().decode(String.self)

        if let date = FITWARDateParsing.fractional.date(from: raw) { return date }
        if let date = FITWARDateParsing.whole.date(from: raw) { return date }
        if let date = FITWARDateParsing.calendarDay.date(from: raw) { return date }

        throw DecodingError.dataCorruptedError(
            in: try decoder.singleValueContainer(),
            debugDescription: "Unrecognised date format: \(raw)"
        )
    }
}

enum FITWARDateParsing {
    static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static let whole: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    /// A challenge-day is a calendar date the server already resolved in the
    /// challenge's timezone — parsed at UTC midnight so it never shifts a day when the
    /// device's own timezone differs.
    static let calendarDay: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()
}
