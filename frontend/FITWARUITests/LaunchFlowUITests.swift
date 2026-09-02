import XCTest

/// Exercises the compiled app as a black box — no mocking here, by definition (that's
/// what the unit tests are for). "Logged in" launches use a REAL refresh token this
/// test obtains by calling the local backend directly (`setUpTestUser`), fed to the
/// app via the DEBUG-only hook in `AppDependencies` — not a fake session.
final class LaunchFlowUITests: XCTestCase {
    private let backendBaseURL = URL(string: "http://localhost:8000")!

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func test_launchWhileLoggedOut_showsWelcomeThenLogin() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-UITestClearSession"]
        app.launch()

        XCTAssertTrue(app.buttons["GET STARTED"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["I already have an account"].exists)

        app.buttons["I already have an account"].tap()
        XCTAssertTrue(app.staticTexts["Welcome back."].waitForExistence(timeout: 10))
    }

    func test_launchWhileLoggedIn_showsMainApplication() throws {
        let refreshToken = try registerFreshTestUserAndGetRefreshToken()

        let app = XCUIApplication()
        app.launchEnvironment["UITEST_SEED_REFRESH_TOKEN"] = refreshToken
        app.launch()

        // Bootstrap validates the seeded token against the real backend before
        // landing on the main app — this is a real session resume, not a UI fake.
        let squadTab = app.tabBars.buttons["SQUAD"]
        XCTAssertTrue(squadTab.waitForExistence(timeout: 8))
        XCTAssertTrue(app.tabBars.buttons["HOME"].exists)
        XCTAssertTrue(app.tabBars.buttons["WARS"].exists)
        XCTAssertTrue(app.tabBars.buttons["BATTLES"].exists)
        XCTAssertTrue(app.tabBars.buttons["YOU"].exists)
    }

    // MARK: - Test setup helper (talks to the local backend directly, not through the app)

    private func registerFreshTestUserAndGetRefreshToken() throws -> String {
        let email = "uitest-\(UUID().uuidString)@example.com"
        var request = URLRequest(url: backendBaseURL.appendingPathComponent("/api/v1/auth/register"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "email": email, "password": "hunter2222", "display_name": "UI Test",
        ])

        let expectation = expectation(description: "register")
        var refreshToken: String?
        URLSession.shared.dataTask(with: request) { data, _, _ in
            if let data, let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                refreshToken = json["refresh_token"] as? String
            }
            expectation.fulfill()
        }.resume()
        wait(for: [expectation], timeout: 10)

        return try XCTUnwrap(refreshToken, "Local backend must be running at \(backendBaseURL) for this test.")
    }
}
