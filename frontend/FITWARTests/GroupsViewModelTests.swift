import Foundation
import Testing
@testable import FITWAR

@MainActor
struct GroupsListViewModelTests {
    private func makeSUT() -> (GroupsListViewModel, MockGroupsService, MockAuthService) {
        let groups = MockGroupsService()
        let auth = MockAuthService()
        let session = SessionManager(
            authService: auth,
            keychain: MockKeychainStore(),
            apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
        )
        return (
            GroupsListViewModel(groupsService: groups, sessionManager: session), groups, auth
        )
    }

    @Test func loadsGroupsIntoLoadedState() async {
        let (sut, groups, _) = makeSUT()
        groups.listResult = .success([Fixture.groupSummary(name: "Squad A")])

        await sut.load()

        #expect(sut.groups.map(\.name) == ["Squad A"])
    }

    @Test func loadedWithNoGroupsIsAnEmptyListNotAnError() async {
        let (sut, groups, _) = makeSUT()
        groups.listResult = .success([])

        await sut.load()

        #expect(sut.state == .loaded([]))
        #expect(sut.groups.isEmpty)
    }

    @Test func networkFailureSurfacesTheNetworkErrorState() async {
        let (sut, groups, _) = makeSUT()
        groups.listResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func serverFailureSurfacesTheServerErrorState() async {
        let (sut, groups, _) = makeSUT()
        groups.listResult = .failure(
            APIError.server(status: 500, code: "INTERNAL_ERROR", detail: "boom")
        )

        await sut.load()

        if case .serverError = sut.state {} else {
            Issue.record("Expected a server error state, got \(sut.state)")
        }
    }

    @Test func createSendsTheDeviceTimezoneAndRefreshesTheList() async {
        let (sut, groups, _) = makeSUT()
        let created = Fixture.groupDetail(name: "New Squad")
        groups.createResult = .success(created)
        groups.listResult = .success([Fixture.groupSummary(id: created.id, name: "New Squad")])
        sut.newGroupName = "New Squad"

        let result = await sut.createGroup()

        #expect(result?.name == "New Squad")
        #expect(groups.createdNames == ["New Squad"])
        // Architecture §11: the group's timezone must be a real IANA identifier.
        #expect(groups.createdTimezones == [TimeZone.current.identifier])
        #expect(sut.groups.map(\.name) == ["New Squad"])
    }

    @Test func createIsBlockedWithoutAName() async {
        let (sut, groups, _) = makeSUT()
        sut.newGroupName = "   "

        #expect(sut.canCreate == false)
        let result = await sut.createGroup()

        #expect(result == nil)
        #expect(groups.createdNames.isEmpty)
    }

    @Test func createFailureShowsCopyAndKeepsTheSheetOpen() async {
        let (sut, groups, _) = makeSUT()
        groups.createResult = .failure(
            APIError.server(status: 400, code: "INVALID_TIMEZONE", detail: "bad tz")
        )
        sut.isCreating = true
        sut.newGroupName = "Squad"

        let result = await sut.createGroup()

        #expect(result == nil)
        #expect(sut.isCreating)
        #expect(sut.actionError == "That timezone isn't recognised. Pick another.")
    }

    @Test func joinPassesTheCodeThrough() async {
        let (sut, groups, _) = makeSUT()
        let joined = Fixture.groupDetail(name: "Joined Squad", myRole: .member)
        groups.joinResult = .success(joined)
        groups.listResult = .success([Fixture.groupSummary(id: joined.id, name: "Joined Squad")])
        sut.joinCode = " k7-xr9 "

        let result = await sut.joinGroup()

        #expect(result?.name == "Joined Squad")
        #expect(groups.joinedCodes == ["k7-xr9"])
    }

    @Test func invalidCodeShowsTheInviteSpecificMessage() async {
        let (sut, groups, _) = makeSUT()
        groups.joinResult = .failure(
            APIError.server(status: 404, code: "INVALID_CODE", detail: "nope")
        )
        sut.joinCode = "ZZ-ZZZ"

        _ = await sut.joinGroup()

        #expect(sut.actionError == "That invite code doesn't match a squad. Check it and try again.")
    }

    @Test func alreadyMemberShowsItsOwnMessageRatherThanARawServerDetail() async {
        let (sut, groups, _) = makeSUT()
        groups.joinResult = .failure(
            APIError.server(status: 409, code: "ALREADY_MEMBER", detail: "raw server text")
        )
        sut.joinCode = "K7-XR9"

        _ = await sut.joinGroup()

        #expect(sut.actionError == "You're already in this squad.")
    }
}

@MainActor
struct GroupDetailViewModelTests {
    private func makeSUT(
        currentUserId: UUID? = nil
    ) -> (GroupDetailViewModel, MockGroupsService, MockChallengesService) {
        let groups = MockGroupsService()
        let challenges = MockChallengesService()
        let session = SessionManager(
            authService: MockAuthService(),
            keychain: MockKeychainStore(),
            apiClient: APIClient(baseURL: URL(string: "https://example.com")!)
        )
        let sut = GroupDetailViewModel(
            groupId: UUID(),
            groupsService: groups,
            challengesService: challenges,
            sessionManager: session,
            currentUserId: currentUserId
        )
        return (sut, groups, challenges)
    }

    @Test func loadsGroupMembersChallengesAndActivityTogether() async {
        let (sut, groups, challenges) = makeSUT()
        groups.fetchResult = .success(Fixture.groupDetail(name: "KITS"))
        groups.membersResult = .success([Fixture.member(displayName: "Ravi", role: .owner)])
        groups.activityResult = .success([
            GroupActivityEntry(
                kind: "member_joined",
                actorDisplayName: "Sai",
                text: "joined the squad",
                occurredAt: Date()
            )
        ])
        challenges.listForGroupResult = .success([Fixture.challengeSummary()])

        await sut.load()

        let content = sut.state.value
        #expect(content?.group.name == "KITS")
        #expect(content?.members.count == 1)
        #expect(content?.challenges.count == 1)
        #expect(content?.activity.count == 1)
    }

    @Test func anyFailedSubRequestFailsTheWholeScreenState() async {
        // Partial content would render as "this squad has no members", which is a lie —
        // better to show the error state the design already provides.
        let (sut, groups, _) = makeSUT()
        groups.fetchResult = .success(Fixture.groupDetail())
        groups.membersResult = .failure(APIError.noConnection)

        await sut.load()

        #expect(sut.state == .networkError)
    }

    @Test func identifiesTheSignedInMember() async {
        let me = UUID()
        let (sut, _, _) = makeSUT(currentUserId: me)

        #expect(sut.isMe(me))
        #expect(sut.isMe(UUID()) == false)
    }

    @Test func rosterDefaultsToTheFirstTab() async {
        let (sut, _, _) = makeSUT()
        #expect(sut.selectedTab == .roster)
        // CHAT joined in Phase 6, once there was a real chat behind it.
        #expect(GroupDetailViewModel.Tab.allCases.map(\.rawValue) == ["ROSTER", "FEED", "CHAT"])
    }

    @Test func ownerCannotLeaveSurfacesTheOwnerMessage() async {
        let (sut, groups, _) = makeSUT()
        groups.leaveError = APIError.server(
            status: 409, code: "OWNER_CANNOT_LEAVE", detail: "raw"
        )

        let didLeave = await sut.leaveGroup()

        #expect(didLeave == false)
        #expect(sut.actionError == "You own this squad, so you can't leave it.")
    }

    @Test func successfulLeaveReportsSuccess() async {
        let (sut, groups, _) = makeSUT()
        groups.leaveError = nil

        let didLeave = await sut.leaveGroup()

        #expect(didLeave)
        #expect(groups.leaveCallCount == 1)
    }
}

struct GroupModelTests {
    @Test func metaLineMatchesTheDesignsMemberChallengeLine() {
        let group = Fixture.groupSummary(memberCount: 8, activeChallengeCount: 3)
        #expect(group.metaLine == "8 MEMBERS · 3 ACTIVE CHALLENGES")
    }

    @Test func metaLineSingularizesCorrectly() {
        let group = Fixture.groupSummary(memberCount: 1, activeChallengeCount: 1)
        #expect(group.metaLine == "1 MEMBER · 1 ACTIVE CHALLENGE")
    }

    @Test func memberStateLabelReportsRealParticipationNotAFakeStreak() {
        #expect(Fixture.member(activeChallengeCount: 0).stateLabel == "NO ACTIVE CHALLENGES")
        #expect(Fixture.member(activeChallengeCount: 1).stateLabel == "IN 1 CHALLENGE")
        #expect(Fixture.member(activeChallengeCount: 3).stateLabel == "IN 3 CHALLENGES")
    }

    @Test func adminRolesAreRecognized() {
        #expect(GroupRole.owner.isAdmin)
        #expect(GroupRole.admin.isAdmin)
        #expect(GroupRole.member.isAdmin == false)
    }

    @Test func relativeTimeFormatsFeedTimestamps() {
        let now = Date(timeIntervalSince1970: 1_760_000_000)
        #expect(RelativeTime.short(from: now.addingTimeInterval(-30), now: now) == "now")
        #expect(RelativeTime.short(from: now.addingTimeInterval(-18 * 60), now: now) == "18m")
        #expect(RelativeTime.short(from: now.addingTimeInterval(-5 * 3600), now: now) == "5h")
        #expect(RelativeTime.short(from: now.addingTimeInterval(-3 * 86_400), now: now) == "3d")
    }
}
