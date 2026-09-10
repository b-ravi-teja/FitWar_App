import SwiftUI

/// The five tabs, frozen by the design spec as `HOME · WARS · BATTLES · SQUAD · YOU`.
enum MainTab: Hashable {
    case home, wars, battles, squad, you
}

/// Bottom nav exactly as approved. Selection is state rather than implicit so a screen
/// can send the user to the tab that resolves their situation — Home's empty state points
/// at WARS and SQUAD rather than naming them and leaving the user to find them.
struct MainTabView: View {
    @State private var selection: MainTab = .home

    var body: some View {
        TabView(selection: $selection) {
            HomeView(selectedTab: $selection)
                .tabItem { tabLabel("HOME", system: "house") }
                .tag(MainTab.home)

            ChallengesListView()
                .tabItem { tabLabel("WARS", system: "flame") }
                .tag(MainTab.wars)

            BattlesListView()
                .tabItem { tabLabel("BATTLES", system: "bolt") }
                .tag(MainTab.battles)

            GroupsListView()
                .tabItem { tabLabel("SQUAD", system: "person.3") }
                .tag(MainTab.squad)

            ProfileView()
                .tabItem { tabLabel("YOU", system: "person.crop.circle") }
                .tag(MainTab.you)
        }
        .tint(FWColor.accent)
    }

    private func tabLabel(_ title: String, system: String) -> some View {
        Label(title, systemImage: system)
    }
}
