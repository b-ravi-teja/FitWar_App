import SwiftUI

/// Bottom nav exactly as approved: HOME · WARS · BATTLES · SQUAD · YOU. WARS and SQUAD
/// are now real, backend-connected screens; Battles remains a shell until the 1v1 phase.
struct MainTabView: View {
    var body: some View {
        TabView {
            HomeView()
                .tabItem { tabLabel("HOME", system: "house") }

            ChallengesListView()
                .tabItem { tabLabel("WARS", system: "flame") }

            BattlesPlaceholderView()
                .tabItem { tabLabel("BATTLES", system: "bolt") }

            GroupsListView()
                .tabItem { tabLabel("SQUAD", system: "person.3") }

            ProfileView()
                .tabItem { tabLabel("YOU", system: "person.crop.circle") }
        }
        .tint(FWColor.accent)
    }

    private func tabLabel(_ title: String, system: String) -> some View {
        Label(title, systemImage: system)
    }
}
