import SwiftUI

@main
struct EarlyBirdApp: App {
    @StateObject private var store = AppStore()
    @StateObject private var permissions = Permissions()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .environmentObject(permissions)
                .tint(.orange)
        }
        .onChange(of: scenePhase) { phase in
            guard phase == .active else { return }
            store.refresh()
            // Picks up permission changes made in the Settings app.
            Task { await permissions.refresh() }
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var permissions: Permissions

    var body: some View {
        tabs
            .fullScreenCover(isPresented: Binding(
                get: { !store.data.hasOnboarded },
                set: { if !$0 { store.data.hasOnboarded = true } }
            )) {
                OnboardingView()
            }
            .task { await permissions.refresh() }
    }

    private var tabs: some View {
        TabView {
            TodayView()
                .tabItem { Label("Today", systemImage: "flame.fill") }
            RewardsView()
                .tabItem { Label("Rewards", systemImage: "gift.fill") }
            HistoryView()
                .tabItem { Label("History", systemImage: "calendar") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
    }
}
