import Foundation
import Testing

@testable import FITWAR

/// Regression tests for the evidence payload's wire format.
///
/// These exist because the first version encoded `Date` with `JSONEncoder`'s default
/// strategy, which emits a bare Double of seconds since Apple's 2001 reference date.
/// The server parsed that as a Unix timestamp, placed the measurement in 1995, and
/// rejected it as outside the challenge window — a failure whose message pointed at
/// timezones rather than at serialization. Unit tests with mocked services could not
/// catch it; only a real request could.
struct EvidenceEncodingTests {
    private func encodedJSON(_ payload: HealthEvidencePayload) throws -> [String: Any] {
        let data = try JSONCoding.encoder.encode(payload)
        return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @Test func encodesInstantsAsISO8601StringsNotNumbers() throws {
        let payload = VerificationFixtures.evidence()

        let json = try encodedJSON(payload)

        let start = try #require(json["period_start"] as? String)
        let end = try #require(json["period_end"] as? String)
        // A number here is the exact bug this guards against.
        #expect(json["period_start"] as? Double == nil)
        #expect(start.contains("T"))
        #expect(start.hasSuffix("Z") || start.contains("+"))
        #expect(end.contains("T"))
    }

    @Test func encodedInstantsRoundTripToTheSameMoment() throws {
        let payload = VerificationFixtures.evidence()

        let json = try encodedJSON(payload)
        let start = try #require(json["period_start"] as? String)
        let parsed = try #require(FITWARDateParsing.whole.date(from: start))

        #expect(abs(parsed.timeIntervalSince(payload.periodStart)) < 1)
    }

    @Test func usesSnakeCaseKeysMatchingTheServerContract() throws {
        let json = try encodedJSON(VerificationFixtures.evidence())

        #expect(json["was_user_entered"] != nil)
        #expect(json["source_name"] != nil)
        #expect(json["period_start"] != nil)
    }

    @Test func sendsTheValueAsAStringToPreserveDecimalPrecision() throws {
        let json = try encodedJSON(VerificationFixtures.evidence(value: "12000.50"))

        // A JSON float would risk 12000.499999 reaching a Numeric(12,2) column.
        #expect(json["value"] as? String == "12000.50")
    }
}
