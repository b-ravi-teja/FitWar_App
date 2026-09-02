import SwiftUI

/// Real shell for Phase 2 (§17) — Home's actual content (active challenges, XP bar,
/// friend activity) depends on the Challenges/XP domains, which are later phases.
/// This is a real, navigable screen using real design-system components, not a
/// blank placeholder — it just has nothing live to show yet.
struct HomeView: View {
    var body: some View {
        NavigationStack {
            EmptyStateView(
                title: "Your battlefield is empty.",
                message: "Once challenges are live, your active wars will show up here."
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(FWColor.background)
            .navigationTitle("Home")
        }
    }
}
