import Foundation
import Testing

@testable import FITWAR

@MainActor
private func makeSession(
    auth: MockAuthService = MockAuthService(),
    keychain: MockKeychainStore = MockKeychainStore()
) -> SessionManager {
    SessionManager(
        authService: auth,
        keychain: keychain,
        apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
    )
}

// MARK: - Routing

@MainActor
struct AppRouteViewModelTests {
    private func makeSUT() -> (AppRouteViewModel, MockUserService) {
        let users = MockUserService()
        return (AppRouteViewModel(userService: users, sessionManager: makeSession()), users)
    }

    @Test func aBrandNewAccountIsRoutedIntoOnboarding() async {
        /// The regression: `AuthFlowView` signalled "just registered" from an
        /// `.onChange` on a view `RootView` replaces the instant the session
        /// authenticates, so the callback lost the race and onboarding was skipped for
        /// every new account. The answer now comes from the server.
        let (sut, users) = makeSUT()
        users.fetchResult = .success(UserFixtures.user(onboardingStage: .discipline))

        await sut.resolve()

        #expect(sut.route == .onboarding(.discipline, displayName: "Ravi"))
    }

    @Test func acompletedAccountGoesStraightToTheApp() async {
        let (sut, users) = makeSUT()
        users.fetchResult = .success(UserFixtures.user(onboardingStage: .completed))

        await sut.resolve()

        #expect(sut.route == .main)
    }

    @Test func aPartiallyOnboardedUserResumesAtTheirStep() async {
        for stage in [OnboardingStage.discipline, .health, .profile] {
            let (sut, users) = makeSUT()
            users.fetchResult = .success(UserFixtures.user(onboardingStage: stage))

            await sut.resolve()

            #expect(sut.route == .onboarding(stage, displayName: "Ravi"))
        }
    }

    @Test func aFailedProfileReadIsItsOwnStateNotAGuess() async {
        /// Falling through to Home would strand a brand-new user on an empty screen with
        /// no HealthKit permission and no route back into the flow.
        let (sut, users) = makeSUT()
        users.fetchResult = .failure(APIError.noConnection)

        await sut.resolve()

        guard case .unavailable = sut.route else {
            Issue.record("expected unavailable, got \(sut.route)")
            return
        }
    }

    @Test func theErrorStateShowsProductCopyNotRawServerText() async {
        let (sut, users) = makeSUT()
        users.fetchResult = .failure(
            APIError.server(status: 422, code: "VALIDATION_ERROR", detail: "body.email: value is not a valid email address")
        )

        await sut.resolve()

        guard case .unavailable(let message) = sut.route else {
            Issue.record("expected unavailable, got \(sut.route)")
            return
        }
        #expect(!message.contains("body."))
    }

    @Test func theRegisteredNameIsCarriedIntoOnboarding() async {
        /// The profile step should not ask for a name the user typed one screen ago.
        let (sut, users) = makeSUT()
        users.fetchResult = .success(
            UserFixtures.user(displayName: "Kiran", onboardingStage: .profile)
        )

        await sut.resolve()

        #expect(sut.route == .onboarding(.profile, displayName: "Kiran"))
    }

    @Test func finishingOnboardingMovesToTheAppWithoutARefetch() async {
        let (sut, users) = makeSUT()
        users.fetchResult = .success(UserFixtures.user(onboardingStage: .profile))
        await sut.resolve()
        let callsAfterResolve = users.fetchCallCount

        sut.onboardingFinished()

        #expect(sut.route == .main)
        #expect(users.fetchCallCount == callsAfterResolve)
    }

    @Test func resetForcesTheNextSessionToResolveAgain() async {
        /// Logging out and back in as a *different* account must not inherit the previous
        /// user's route.
        let (sut, users) = makeSUT()
        users.fetchResult = .success(UserFixtures.user(onboardingStage: .completed))
        await sut.resolve()

        sut.reset()

        #expect(sut.route == .resolving)
    }

    @Test func anUnknownStageFromANewerServerFailsSafeToTheApp() throws {
        /// Guessing "completed" sends the user somewhere recoverable; guessing an
        /// onboarding step would trap them in a flow this build cannot finish.
        let json = #"{"onboarding_stage": "some_future_step"}"#
        struct Wrapper: Decodable { let onboardingStage: OnboardingStage }

        let decoded = try JSONCoding.decoder.decode(Wrapper.self, from: Data(json.utf8))

        #expect(decoded.onboardingStage == .completed)
    }
}

// MARK: - Onboarding flow

@MainActor
struct OnboardingViewModelTests {
    private func makeSUT(
        startingAt stage: OnboardingStage = .discipline
    ) -> (OnboardingViewModel, MockUserService, MockHealthKitService) {
        let users = MockUserService()
        users.updateResult = .success(UserFixtures.user())
        let health = MockHealthKitService()
        let sut = OnboardingViewModel(
            userService: users,
            sessionManager: makeSession(),
            health: health,
            startingAt: stage
        )
        return (sut, users, health)
    }

    @Test func itStartsAtTheStepTheServerReported() {
        #expect(makeSUT(startingAt: .health).0.step == .health)
        #expect(makeSUT(startingAt: .profile).0.step == .profile)
    }

    @Test func aCompletedStageResolvesToTheLastRealStep() {
        /// Should never happen — the router sends completed users to Home — but resuming
        /// at a real step beats rendering a step that does not exist.
        #expect(makeSUT(startingAt: .completed).0.step == .profile)
    }

    @Test func eachStepIsPersistedServerSideAsItIsPassed() async {
        /// Progress that is not persisted is progress the user loses when they quit.
        let (sut, users, _) = makeSUT()

        await sut.pickDiscipline("Steps")
        await sut.connectHealth()

        #expect(users.recordedStages == [.health, .profile])
    }

    @Test func healthKitAuthorizationIsActuallyRequested() async {
        /// The step previously called `UnimplementedHealthConnector`, a Phase 2 stand-in
        /// that made no HealthKit call — so permission was never requested even when
        /// onboarding did run.
        let (sut, _, health) = makeSUT(startingAt: .health)

        await sut.connectHealth()

        #expect(health.requestedActivities == [.steps])
    }

    @Test func thePromptAsksForTheMetricTheChosenDisciplineUses() async {
        let (sut, _, health) = makeSUT()
        await sut.pickDiscipline("Running")

        await sut.connectHealth()

        #expect(health.requestedActivities == [.distance])
    }

    @Test func adisciplineHealthKitCannotMeasureFallsBackToSteps() async {
        /// Push-ups have no HealthKit type; requesting one would throw rather than prompt.
        let (sut, _, health) = makeSUT()
        await sut.pickDiscipline("Strength")

        await sut.connectHealth()

        #expect(health.requestedActivities == [.steps])
    }

    @Test func aDeniedOrUnavailableHealthKitStillAdvances() async {
        /// iOS never reports whether *read* access was granted, so there is no denial to
        /// branch on — blocking here would strand the user on an unknowable outcome.
        let (sut, _, health) = makeSUT(startingAt: .health)
        health.requestResult = .failure(HealthKitError.unavailable)

        await sut.connectHealth()

        #expect(sut.step == .profile)
        #expect(sut.healthUnavailable)
    }

    @Test func skippingHealthAdvancesAndRecordsProgress() async {
        let (sut, users, health) = makeSUT(startingAt: .health)

        await sut.skipHealth()

        #expect(sut.step == .profile)
        #expect(users.recordedStages == [.profile])
        #expect(health.requestedActivities.isEmpty)
    }

    @Test func finishingSavesTheNameThenMarksOnboardingComplete() async {
        let (sut, users, _) = makeSUT(startingAt: .profile)
        sut.displayName = "  Ravi  "

        let ok = await sut.finish()

        #expect(ok)
        #expect(users.updatedDisplayNames == ["Ravi"])
        #expect(users.recordedStages == [.completed])
    }

    @Test func aFailedNameSaveDoesNotMarkOnboardingComplete() async {
        /// Otherwise a failed save strands the user with a half-finished profile and no
        /// way back into the flow.
        let (sut, users, _) = makeSUT(startingAt: .profile)
        users.updateResult = .failure(APIError.noConnection)
        sut.displayName = "Ravi"

        let ok = await sut.finish()

        #expect(!ok)
        #expect(users.recordedStages.isEmpty)
        #expect(sut.errorMessage != nil)
    }

    @Test func anEmptyNameCannotFinish() async {
        let (sut, _, _) = makeSUT(startingAt: .profile)
        sut.displayName = "   "

        #expect(!sut.canFinish)
        #expect(!(await sut.finish()))
    }

    @Test func aFailedProgressWriteStillLetsTheUserContinue() async {
        /// A network blip must not block onboarding; the next successful write or
        /// `finish()` brings the server back in line.
        let (sut, users, _) = makeSUT()
        users.onboardingResult = .failure(APIError.noConnection)

        await sut.pickDiscipline("Steps")

        #expect(sut.step == .health)
    }
}
