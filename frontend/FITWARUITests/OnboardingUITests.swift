import XCTest

/// Basic onboarding navigation (this phase's §21) — scoped to navigation only, not a
/// full backend-dependent registration-through-onboarding run, so it stays fast and
/// doesn't depend on the discipline/health steps' specific copy changing later.
final class OnboardingUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func test_getStartedNavigatesToRegisterScreen() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-UITestClearSession"]
        app.launch()

        XCTAssertTrue(app.buttons["GET STARTED"].waitForExistence(timeout: 10))
        app.buttons["GET STARTED"].tap()

        XCTAssertTrue(app.staticTexts["Create your account"].waitForExistence(timeout: 10))
    }

    func test_registerBackButtonReturnsToWelcome() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-UITestClearSession"]
        app.launch()

        XCTAssertTrue(app.buttons["GET STARTED"].waitForExistence(timeout: 10))
        app.buttons["GET STARTED"].tap()
        XCTAssertTrue(app.staticTexts["Create your account"].waitForExistence(timeout: 10))

        app.buttons["Back"].tap()
        XCTAssertTrue(app.buttons["GET STARTED"].waitForExistence(timeout: 10))
    }
}
