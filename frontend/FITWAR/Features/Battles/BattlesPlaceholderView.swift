import SwiftUI

/// Real shell for Phase 2 (§17) — 1v1 battle logic is a later phase.
struct BattlesPlaceholderView: View {
    var body: some View {
        NavigationStack {
            EmptyStateView(
                title: "No battles yet.",
                message: "1v1 battles arrive in a later phase."
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(FWColor.background)
            .navigationTitle("Battles")
        }
    }
}
