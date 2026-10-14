import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var permissions: Permissions
    @State private var unlocked = false
    @State private var savingSpot = false
    @State private var spotError: String?
    @State private var showingUnlock = false
    @State private var showingNewPIN = false
    @State private var confirmingReset = false

    private var locked: Bool { store.data.settings.parentPIN != nil && !unlocked }

    var body: some View {
        NavigationStack {
            Group {
                if locked {
                    VStack(spacing: 16) {
                        Image(systemName: "lock.fill").font(.system(size: 48)).foregroundStyle(.orange)
                        Text("Settings are locked").font(.title2.bold())
                        Text("A grown-up can unlock them with the parent code.")
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("Unlock") { showingUnlock = true }
                            .buttonStyle(.borderedProminent)
                    }
                    .padding()
                } else {
                    form
                }
            }
            .navigationTitle("Settings")
            .sheet(isPresented: $showingUnlock) {
                PINEntryView(title: "Parent code") { code in
                    guard code == store.data.settings.parentPIN else { return false }
                    unlocked = true
                    return true
                }
            }
            .sheet(isPresented: $showingNewPIN) {
                PINEntryView(title: "Choose a 4-digit code") { code in
                    store.data.settings.parentPIN = code
                    unlocked = true
                    return true
                }
            }
        }
    }

    private var form: some View {
        Form {
            Section {
                DatePicker("First bell", selection: timeBinding(\.schoolStartHour, \.schoolStartMinute), displayedComponents: .hourAndMinute)
                Stepper("Early = \(store.data.settings.earlyMinutes) min before", value: $store.data.settings.earlyMinutes, in: 0...60, step: 5)
            } header: {
                Text("School")
            } footer: {
                let deadline = StreakEngine.earlyDeadline(on: store.today, settings: store.data.settings)
                Text("Arrive by \(deadline.formatted(date: .omitted, time: .shortened)) to count as early.")
            }

            Section("School days") {
                ForEach([2, 3, 4, 5, 6, 7, 1], id: \.self) { weekday in
                    Toggle(Calendar.current.weekdaySymbols[weekday - 1], isOn: schoolDayBinding(weekday))
                }
            }

            Section {
                Toggle("Morning reminder", isOn: reminderBinding(\.reminderEnabled))
                if store.data.settings.reminderEnabled {
                    DatePicker("Remind me at", selection: timeBinding(\.reminderHour, \.reminderMinute), displayedComponents: .hourAndMinute)
                }
                if store.data.settings.reminderEnabled && permissions.notificationStatus == .denied {
                    Button("Notifications are off. Turn them on in Settings") { permissions.openSystemSettings() }
                        .foregroundStyle(.red)
                }
            } header: {
                Text("Reminders")
            }

            Section {
                PermissionRow(
                    title: "Location",
                    granted: permissions.locationAllowed,
                    denied: permissions.locationDenied,
                    request: { permissions.requestLocation() },
                    openSettings: { permissions.openSystemSettings() }
                )
                if store.data.settings.hasSchoolLocation {
                    Label("School spot saved", systemImage: "mappin.circle.fill")
                    Toggle("Only allow check-in at school", isOn: $store.data.settings.requireAtSchool)
                    Picker("Counts as school within", selection: $store.data.settings.schoolRadius) {
                        Text("100 m").tag(100.0)
                        Text("250 m").tag(250.0)
                        Text("500 m").tag(500.0)
                        Text("1 km").tag(1000.0)
                    }
                }
                if permissions.locationAllowed {
                    Button(savingSpot ? "Finding you..." : (store.data.settings.hasSchoolLocation ? "Move school spot to where I am" : "I'm at school now: save this spot")) {
                        Task { await saveSpot() }
                    }
                    .disabled(savingSpot)
                }
                if store.data.settings.hasSchoolLocation {
                    Button("Forget school spot", role: .destructive) { store.clearSchoolLocation() }
                }
                if let spotError {
                    Text(spotError).foregroundStyle(.red).font(.footnote)
                }
            } header: {
                Text("School location")
            } footer: {
                Text("When a school spot is saved, \"I'm at school!\" only works there. Location is checked only when you tap the button.")
            }

            Section {
                PermissionRow(
                    title: "Notifications",
                    granted: permissions.notificationsAllowed,
                    denied: permissions.notificationStatus == .denied,
                    request: { Task { await permissions.requestNotifications() } },
                    openSettings: { permissions.openSystemSettings() }
                )
                Button("Run setup again") { store.data.hasOnboarded = false }
            } header: {
                Text("Permissions")
            }

            Section {
                if store.data.settings.parentPIN == nil {
                    Button("Set parent code") { showingNewPIN = true }
                } else {
                    Button("Change parent code") { showingNewPIN = true }
                    Button("Remove parent code", role: .destructive) { store.data.settings.parentPIN = nil }
                    Button("Lock now") { unlocked = false }
                }
            } header: {
                Text("Parent controls")
            } footer: {
                Text("With a code set, only a grown-up can change settings, edit history, add rewards or mark rewards as used.")
            }

            Section {
                Button("Erase streaks, points and rewards", role: .destructive) { confirmingReset = true }
                    .confirmationDialog("Erase all history and points? Your settings stay.", isPresented: $confirmingReset, titleVisibility: .visible) {
                        Button("Erase everything", role: .destructive) { store.resetEverything() }
                    }
            } footer: {
                Text("Points: 10 for each early day, +2 more for every day in a row (up to +20), and a bonus every 5 days. Late arrivals still earn 2.")
            }
        }
    }

    private func saveSpot() async {
        savingSpot = true
        defer { savingSpot = false }
        if let here = await permissions.currentLocation() {
            store.setSchoolLocation(here)
            spotError = nil
        } else {
            spotError = "Couldn't find your location. Try again in a moment."
        }
    }

    // MARK: Bindings

    private func timeBinding(_ hour: WritableKeyPath<Settings, Int>, _ minute: WritableKeyPath<Settings, Int>) -> Binding<Date> {
        Binding(
            get: { store.today.at(hour: store.data.settings[keyPath: hour], minute: store.data.settings[keyPath: minute]) },
            set: { date in
                let c = Calendar.current.dateComponents([.hour, .minute], from: date)
                store.data.settings[keyPath: hour] = c.hour ?? 0
                store.data.settings[keyPath: minute] = c.minute ?? 0
                Reminders.update(for: store.data.settings)
            }
        )
    }

    private func schoolDayBinding(_ weekday: Int) -> Binding<Bool> {
        Binding(
            get: { store.data.settings.schoolDays.contains(weekday) },
            set: { on in
                if on { store.data.settings.schoolDays.insert(weekday) } else { store.data.settings.schoolDays.remove(weekday) }
                Reminders.update(for: store.data.settings)
            }
        )
    }

    private func reminderBinding(_ key: WritableKeyPath<Settings, Bool>) -> Binding<Bool> {
        Binding(
            get: { store.data.settings[keyPath: key] },
            set: { value in
                store.data.settings[keyPath: key] = value
                Reminders.update(for: store.data.settings)
            }
        )
    }
}

/// Shows whether a permission is on, with the right button to fix it: ask (first time) or open Settings (after a "no").
private struct PermissionRow: View {
    var title: String
    var granted: Bool
    var denied: Bool
    var request: () -> Void
    var openSettings: () -> Void

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            if granted {
                Label("Allowed", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            } else if denied {
                Button("Open Settings", action: openSettings)
            } else {
                Button("Allow", action: request)
                    .buttonStyle(.borderedProminent)
            }
        }
    }
}
