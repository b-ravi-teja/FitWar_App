import XCTest

/// The Phase 3 critical path, end to end against the REAL local FastAPI backend:
/// login → Squads → create squad → create challenge → challenge detail.
///
/// Nothing here is mocked. The session is a genuine refresh token obtained by
/// registering against the local backend, and every screen assertion below is reading
/// data the server actually returned.
final class GroupsChallengesUITests: XCTestCase {
    private let backendBaseURL = URL(string: "http://localhost:8000")!
    private let timeout: TimeInterval = 15

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func test_criticalPath_createSquadThenChallengeThenSeeDetail() throws {
        let app = try launchLoggedIn()

        // ── Squads tab: starts genuinely empty for a brand-new account ──
        app.tabBars.buttons["SQUAD"].tap()
        XCTAssertTrue(
            app.staticTexts["Squads"].waitForExistence(timeout: timeout),
            "Squads list should replace the Phase 2 placeholder"
        )
        XCTAssertTrue(app.staticTexts["No squad yet."].waitForExistence(timeout: timeout))

        // ── Create a squad ──
        app.buttons["CREATE A SQUAD"].tap()
        let nameField = app.textFields["Squad name"]
        XCTAssertTrue(nameField.waitForExistence(timeout: timeout))
        nameField.tap()
        nameField.typeText("KITS FITNESS WAR")
        app.buttons["CREATE SQUAD"].tap()

        // Landing on the group screen means the POST succeeded and the detail read back.
        XCTAssertTrue(
            app.staticTexts["KITS FITNESS WAR"].waitForExistence(timeout: timeout),
            "Creating a squad should navigate into it"
        )
        XCTAssertTrue(app.buttons["ROSTER"].waitForExistence(timeout: timeout))
        XCTAssertTrue(app.buttons["FEED"].exists)

        // The join code is real server-generated data, not a placeholder.
        XCTAssertTrue(app.otherElements["Join code"].waitForExistence(timeout: timeout))

        // ── Create a challenge in it ──
        app.tabBars.buttons["WARS"].tap()
        XCTAssertTrue(app.staticTexts["Challenges"].waitForExistence(timeout: timeout))

        app.buttons["Create a challenge"].tap()
        XCTAssertTrue(app.staticTexts["Pick the activity"].waitForExistence(timeout: timeout))

        app.buttons["Steps"].tap()
        app.buttons["CONTINUE"].tap()

        XCTAssertTrue(app.staticTexts["Choose the game mode"].waitForExistence(timeout: timeout))
        // ModeSelectCard combines its children for VoiceOver, so the mode is a button
        // label rather than a standalone static text.
        XCTAssertTrue(
            app.buttons.containing(NSPredicate(format: "label CONTAINS 'SURVIVAL'")).count > 0
        )
        app.buttons["CONTINUE"].tap()

        XCTAssertTrue(app.staticTexts["Set the rules"].waitForExistence(timeout: timeout))
        app.buttons["CONTINUE"].tap()

        XCTAssertTrue(app.staticTexts["Invite your squad"].waitForExistence(timeout: timeout))
        app.buttons["CONTINUE"].tap()

        XCTAssertTrue(app.staticTexts["Ready to declare war?"].waitForExistence(timeout: timeout))
        app.buttons["START CHALLENGE"].tap()

        // ── Challenge detail, populated from the create response ──
        XCTAssertTrue(
            app.staticTexts["30 DAY STEPS WAR"].waitForExistence(timeout: timeout),
            "Starting a challenge should land on its detail screen with real data"
        )
        XCTAssertTrue(app.staticTexts["PARTICIPANTS"].waitForExistence(timeout: timeout))
        // Day 1 of 30, and the SURVIVAL failure rule — both computed server-side.
        XCTAssertTrue(app.staticTexts["DAY 1 / 30 · MISS TWICE → ELIMINATED"].exists)
    }

    func test_invalidJoinCodeShowsAnError() throws {
        let app = try launchLoggedIn()

        app.tabBars.buttons["SQUAD"].tap()
        XCTAssertTrue(app.staticTexts["No squad yet."].waitForExistence(timeout: timeout))

        app.buttons["JOIN WITH A CODE"].tap()
        let codeField = app.textFields["Join code"]
        XCTAssertTrue(codeField.waitForExistence(timeout: timeout))
        codeField.tap()
        codeField.typeText("ZZ-ZZZ")
        app.buttons["JOIN SQUAD"].tap()

        // A real 404 INVALID_CODE from the backend, rendered through the shared
        // error-copy mapping rather than a raw server sentence.
        // FWTextField prefixes its inline error for VoiceOver, so the accessible label
        // carries the "Error: " prefix that a sighted user doesn't see.
        XCTAssertTrue(
            app.staticTexts[
                "Error: That invite code doesn't match a squad. Check it and try again."
            ].waitForExistence(timeout: timeout)
        )
    }

    func test_challengesTabIsEmptyWithoutASquad() throws {
        let app = try launchLoggedIn()

        app.tabBars.buttons["WARS"].tap()

        XCTAssertTrue(app.staticTexts["Challenges"].waitForExistence(timeout: timeout))
        XCTAssertTrue(app.staticTexts["Join a squad first."].waitForExistence(timeout: timeout))
    }

    // MARK: - Helpers

    private func launchLoggedIn() throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["UITEST_SEED_REFRESH_TOKEN"] =
            try registerFreshTestUserAndGetRefreshToken()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["SQUAD"].waitForExistence(timeout: timeout))
        return app
    }

    private func registerFreshTestUserAndGetRefreshToken() throws -> String {
        let email = "uitest-\(UUID().uuidString)@example.com"
        var request = URLRequest(
            url: backendBaseURL.appendingPathComponent("/api/v1/auth/register")
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "email": email, "password": "hunter2222", "display_name": "UI Test",
        ])

        let expectation = expectation(description: "register")
        var refreshToken: String?
        URLSession.shared.dataTask(with: request) { data, _, _ in
            if let data,
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                refreshToken = json["refresh_token"] as? String
            }
            expectation.fulfill()
        }.resume()
        wait(for: [expectation], timeout: 15)

        return try XCTUnwrap(
            refreshToken,
            "Local backend must be running at \(backendBaseURL) for this test."
        )
    }
}
