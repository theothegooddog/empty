import SwiftUI

struct HistoryView: View {
    @EnvironmentObject private var store: AppStore
    @State private var showingAdd = false
    @State private var gated: (() -> Void)?

    private var visibleResults: [DayResult] {
        store.summary.results.reversed().filter { $0.status != .off || store.data.daysOff.contains($0.day) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        StatTile(value: "\(earlyCount)", label: "Early days")
                        StatTile(value: "\(store.summary.best)", label: "Best streak")
                        StatTile(value: "\(store.summary.totalEarned)", label: "Points earned")
                    }
                }

                Section {
                    ForEach(visibleResults) { result in
                        HistoryRow(result: result)
                            .swipeActions(edge: .trailing) {
                                if result.arrival != nil {
                                    Button("Delete", role: .destructive) {
                                        store.protected($gated) { store.removeCheckIn(on: result.day) }
                                    }
                                }
                                Button(store.data.daysOff.contains(result.day) ? "School day" : "Day off") {
                                    store.protected($gated) { store.toggleDayOff(result.day) }
                                }
                                .tint(.indigo)
                            }
                    }
                } footer: {
                    Text("Swipe a day to mark it as a holiday or sick day. Days off never break your streak.")
                }
            }
            .navigationTitle("History")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        store.protected($gated) { showingAdd = true }
                    } label: {
                        Label("Log a day", systemImage: "plus")
                    }
                }
            }
            .sheet(isPresented: $showingAdd) { LogDayView() }
            .parentGate($gated)
        }
    }

    private var earlyCount: Int {
        store.summary.results.filter { $0.status == .early }.count
    }
}

private struct StatTile: View {
    var value: String
    var label: String

    var body: some View {
        VStack(spacing: 2) {
            Text(value).font(.title2.bold().monospacedDigit())
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct HistoryRow: View {
    var result: DayResult

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: result.status.symbol)
                .font(.title3)
                .foregroundStyle(result.status.color)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(result.day.noon().formatted(.dateTime.weekday(.wide).month().day()))
                    .font(.body)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if result.points > 0 {
                Text("+\(result.points)")
                    .font(.subheadline.bold().monospacedDigit())
                    .foregroundStyle(.orange)
            }
        }
    }

    private var subtitle: String {
        var parts = [result.status.label]
        if let arrival = result.arrival {
            parts.append(arrival.formatted(date: .omitted, time: .shortened))
        }
        if result.status == .early {
            parts.append("streak \(result.streak)")
        }
        if result.milestoneBonus > 0 {
            parts.append("bonus +\(result.milestoneBonus)")
        }
        return parts.joined(separator: " · ")
    }
}

/// Lets a parent record a day the kid forgot to tap the button.
private struct LogDayView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()
    @State private var time = Date()

    var body: some View {
        NavigationStack {
            Form {
                DatePicker("Day", selection: $date, in: ...Date(), displayedComponents: .date)
                DatePicker("Arrived at", selection: $time, displayedComponents: .hourAndMinute)
                Section {
                    Text(preview).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Log a day")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        store.setCheckIn(day: Day(date), arrival: arrival)
                        dismiss()
                    }
                }
            }
        }
        .onAppear {
            let s = store.data.settings
            time = Day(Date()).at(hour: s.schoolStartHour, minute: s.schoolStartMinute)
                .addingTimeInterval(-Double(s.earlyMinutes * 60))
        }
    }

    private var arrival: Date {
        let c = Calendar.current.dateComponents([.hour, .minute], from: time)
        return Day(date).at(hour: c.hour ?? 0, minute: c.minute ?? 0)
    }

    private var preview: String {
        let early = StreakEngine.isEarly(arrival, on: Day(date), settings: store.data.settings)
        return early ? "This counts as an early arrival." : "This counts as late."
    }
}
