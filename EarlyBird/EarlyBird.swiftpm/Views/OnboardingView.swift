import SwiftUI

/// First-launch setup: bell time, then asks for notification and location permission, one step at a time.
struct OnboardingView: View {
    @EnvironmentObject private var store: AppStore
    @EnvironmentObject private var permissions: Permissions

    private enum Step: Int, CaseIterable { case welcome, bell, notifications, location, done }
    @State private var step: Step = .welcome
    @State private var savingSpot = false
    @State private var spotMessage: String?

    var body: some View {
        VStack(spacing: 0) {
            ProgressView(value: Double(step.rawValue), total: Double(Step.allCases.count - 1))
                .tint(.orange)
                .padding()

            ScrollView {
                VStack(spacing: 20) {
                    switch step {
                    case .welcome: welcome
                    case .bell: bell
                    case .notifications: notifications
                    case .location: location
                    case .done: done
                    }
                }
                .padding(24)
                .frame(maxWidth: 500)
                .frame(maxWidth: .infinity)
            }

            footer
                .padding(24)
        }
        .animation(.default, value: step)
        .interactiveDismissDisabled()
    }

    // MARK: Steps

    private var welcome: some View {
        StepHeader(symbol: "flame.fill", title: "Welcome to Early Bird", text: "Get to school early, build a streak, and earn points you can trade for screen time, game coins and other rewards.")
    }

    private var bell: some View {
        VStack(spacing: 20) {
            StepHeader(symbol: "bell.fill", title: "When does school start?", text: "Arrive early enough before the first bell to keep your streak going.")
            VStack(spacing: 12) {
                DatePicker("First bell", selection: bellBinding, displayedComponents: .hourAndMinute)
                Stepper("Early = \(store.data.settings.earlyMinutes) min before", value: $store.data.settings.earlyMinutes, in: 0...60, step: 5)
            }
            .padding()
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
        }
    }

    private var notifications: some View {
        VStack(spacing: 20) {
            StepHeader(symbol: "alarm.fill", title: "Morning reminders", text: "Get a nudge on school mornings so you leave on time. You can change the time later in Settings.")
            DatePicker("Remind me at", selection: reminderBinding, displayedComponents: .hourAndMinute)
                .padding()
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))

            if permissions.notificationsAllowed {
                PermissionBadge(granted: true, text: "Reminders are on")
            } else if permissions.notificationStatus == .denied {
                PermissionBadge(granted: false, text: "Notifications are off for Early Bird")
                Button("Open Settings") { permissions.openSystemSettings() }
            } else {
                Button {
                    Task {
                        if await permissions.requestNotifications() {
                            store.data.settings.reminderEnabled = true
                            Reminders.update(for: store.data.settings)
                        }
                    }
                } label: {
                    Label("Turn on reminders", systemImage: "bell.badge.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        }
    }

    private var location: some View {
        VStack(spacing: 20) {
            StepHeader(symbol: "location.fill", title: "Prove you made it", text: "Early Bird uses your location only when you tap \"I'm at school!\" to check you're really there. It's never tracked in the background.")

            if permissions.locationAllowed {
                PermissionBadge(granted: true, text: "Location is allowed")
                VStack(spacing: 8) {
                    Button {
                        Task { await saveSpot() }
                    } label: {
                        Label(savingSpot ? "Finding you..." : "I'm at school now: save this spot", systemImage: "mappin.and.ellipse")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(savingSpot)
                    Text(spotMessage ?? "Not at school right now? Save the spot later in Settings, the first time you're there.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            } else if permissions.locationDenied {
                PermissionBadge(granted: false, text: "Location is off for Early Bird")
                Button("Open Settings") { permissions.openSystemSettings() }
                Text("Without location, check-ins aren't verified. A grown-up can still turn this on later.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            } else {
                Button {
                    permissions.requestLocation()
                } label: {
                    Label("Allow location", systemImage: "location.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        }
    }

    private var done: some View {
        StepHeader(symbol: "checkmark.seal.fill", title: "You're all set!", text: "Tap \"I'm at school!\" each morning when you arrive. Tip: ask a grown-up to set a parent code in Settings.")
    }

    // MARK: Footer

    private var footer: some View {
        HStack {
            if step != .welcome && step != .done {
                Button("Back") { step = Step(rawValue: step.rawValue - 1) ?? .welcome }
            }
            Spacer()
            Button(primaryTitle) {
                if step == .done {
                    store.data.hasOnboarded = true
                } else {
                    step = Step(rawValue: step.rawValue + 1) ?? .done
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    private var primaryTitle: String {
        switch step {
        case .welcome: return "Let's go"
        case .notifications where !permissions.notificationsAllowed: return "Skip"
        case .location where !permissions.locationAllowed: return "Skip"
        case .done: return "Start my streak"
        default: return "Next"
        }
    }

    // MARK: Helpers

    private func saveSpot() async {
        savingSpot = true
        defer { savingSpot = false }
        if let here = await permissions.currentLocation() {
            store.setSchoolLocation(here)
            spotMessage = "Saved! Check-ins now only work at school."
        } else {
            spotMessage = "Couldn't find your location. Try again in a moment."
        }
    }

    private var bellBinding: Binding<Date> {
        Binding(
            get: { store.today.at(hour: store.data.settings.schoolStartHour, minute: store.data.settings.schoolStartMinute) },
            set: {
                let c = Calendar.current.dateComponents([.hour, .minute], from: $0)
                store.data.settings.schoolStartHour = c.hour ?? 8
                store.data.settings.schoolStartMinute = c.minute ?? 30
            }
        )
    }

    private var reminderBinding: Binding<Date> {
        Binding(
            get: { store.today.at(hour: store.data.settings.reminderHour, minute: store.data.settings.reminderMinute) },
            set: {
                let c = Calendar.current.dateComponents([.hour, .minute], from: $0)
                store.data.settings.reminderHour = c.hour ?? 7
                store.data.settings.reminderMinute = c.minute ?? 0
                Reminders.update(for: store.data.settings)
            }
        )
    }
}

private struct StepHeader: View {
    var symbol: String
    var title: String
    var text: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: symbol)
                .font(.system(size: 64))
                .foregroundStyle(.orange)
                .padding(.top, 24)
            Text(title)
                .font(.largeTitle.bold())
                .multilineTextAlignment(.center)
            Text(text)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
    }
}

struct PermissionBadge: View {
    var granted: Bool
    var text: String

    var body: some View {
        Label(text, systemImage: granted ? "checkmark.circle.fill" : "xmark.circle.fill")
            .font(.headline)
            .foregroundStyle(granted ? .green : .red)
    }
}
