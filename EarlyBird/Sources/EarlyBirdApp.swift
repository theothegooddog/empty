import SwiftUI

@main
struct EarlyBirdApp: App {
    @StateObject private var store = AppStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .tint(.orange)
        }
        .onChange(of: scenePhase) { phase in
            if phase == .active { store.refresh() }
        }
    }
}

struct ContentView: View {
    var body: some View {
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
