import SwiftUI

struct TodayView: View {
    @EnvironmentObject private var store: AppStore
    @State private var celebration: DayResult?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    StreakHero(current: store.summary.current, best: store.summary.best)
                    TodayCard(onCheckIn: checkIn)
                    MilestoneCard(streak: store.summary.current)
                    WeekStrip(results: Array(store.summary.results.suffix(7)))
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Early Bird")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    PointsChip(points: store.balance)
                }
            }
            .sheet(item: $celebration) { result in
                CelebrationView(result: result)
            }
        }
    }

    private func checkIn() {
        let generator = UINotificationFeedbackGenerator()
        if let result = store.checkInNow() {
            generator.notificationOccurred(result.status == .early ? .success : .warning)
            celebration = result
        }
    }
}

struct PointsChip: View {
    var points: Int

    var body: some View {
        Label("\(points)", systemImage: "star.circle.fill")
            .font(.subheadline.bold().monospacedDigit())
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(.orange.opacity(0.15), in: Capsule())
            .foregroundStyle(.orange)
            .accessibilityLabel("\(points) points")
    }
}

private struct StreakHero: View {
    var current: Int
    var best: Int

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: current > 0 ? "flame.fill" : "flame")
                .font(.system(size: 72))
                .foregroundStyle(
                    current > 0
                        ? AnyShapeStyle(LinearGradient(colors: [.yellow, .orange, .red], startPoint: .top, endPoint: .bottom))
                        : AnyShapeStyle(Color.secondary)
                )
            Text("\(current)")
                .font(.system(size: 64, weight: .heavy, design: .rounded).monospacedDigit())
                .contentTransition(.numericText())
            Text(current == 1 ? "day early in a row" : "days early in a row")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("Best streak: \(best)")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 24))
    }
}

private struct TodayCard: View {
    @EnvironmentObject private var store: AppStore
    var onCheckIn: () -> Void

    var body: some View {
        let settings = store.data.settings
        let today = store.today
        let deadline = StreakEngine.earlyDeadline(on: today, settings: settings)
        let result = store.todayResult

        VStack(alignment: .leading, spacing: 14) {
            Text("Today").font(.title3.bold())

            switch result?.status {
            case .early:
                StatusRow(
                    symbol: "checkmark.seal.fill", color: .green,
                    title: "You beat the bell!",
                    detail: arrivalDetail(result, settings: settings) + " · +\(result?.points ?? 0) points"
                )
            case .late:
                StatusRow(
                    symbol: "clock.badge.exclamationmark.fill", color: .orange,
                    title: "Checked in, but not early",
                    detail: arrivalDetail(result, settings: settings) + " · +\(result?.points ?? 0) points. New streak starts tomorrow."
                )
            case .off:
                StatusRow(
                    symbol: "sun.max.fill", color: .yellow,
                    title: "No school today",
                    detail: "Your streak is safe. Enjoy the day off!"
                )
            default:
                StatusRow(
                    symbol: "alarm.fill", color: .orange,
                    title: "Get there by \(deadline.formatted(date: .omitted, time: .shortened))",
                    detail: "That's \(settings.earlyMinutes) min before the bell. Tap the button when you arrive."
                )
                Button(action: onCheckIn) {
                    Label("I'm at school!", systemImage: "figure.walk.arrival")
                        .font(.title3.bold())
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))
    }

    private func arrivalDetail(_ result: DayResult?, settings: Settings) -> String {
        guard let result, let arrival = result.arrival else { return "" }
        let time = arrival.formatted(date: .omitted, time: .shortened)
        let minutes = StreakEngine.minutesBeforeBell(arrival, on: result.day, settings: settings)
        if minutes > 0 { return "Arrived \(time), \(minutes) min before the bell" }
        if minutes == 0 { return "Arrived \(time), right at the bell" }
        return "Arrived \(time), \(-minutes) min after the bell"
    }
}

private struct StatusRow: View {
    var symbol: String
    var color: Color
    var title: String
    var detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(color)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }
}

private struct MilestoneCard: View {
    var streak: Int

    var body: some View {
        let target = PointsRules.nextMilestone(after: streak)
        let previous = target - PointsRules.milestoneEvery
        let progress = Double(streak - previous) / Double(PointsRules.milestoneEvery)
        let toGo = target - streak

        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Next bonus").font(.headline)
                Spacer()
                Text("+\(PointsRules.milestoneBonus(streak: target)) pts")
                    .font(.headline.monospacedDigit())
                    .foregroundStyle(.orange)
            }
            ProgressView(value: progress)
                .tint(.orange)
            Text("\(toGo) more early \(toGo == 1 ? "day" : "days") to reach a \(target)-day streak")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))
    }
}

private struct WeekStrip: View {
    var results: [DayResult]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Last 7 days").font(.headline)
            HStack {
                ForEach(results) { result in
                    VStack(spacing: 6) {
                        Text(result.day.noon().formatted(.dateTime.weekday(.narrow)))
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                        Image(systemName: result.status.symbol)
                            .font(.title3)
                            .foregroundStyle(result.status.color)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
        }
        .padding()
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))
    }
}

private struct CelebrationView: View {
    var result: DayResult
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 18) {
            Text(result.status == .early ? "🔥" : "👍")
                .font(.system(size: 90))
            Text(result.status == .early ? "Early bird!" : "You made it!")
                .font(.largeTitle.bold())
            if result.status == .early {
                Text("\(result.streak)-day streak")
                    .font(.title2)
            } else {
                Text("Not early this time, so the streak resets. Tomorrow's a fresh start.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }
            Text("+\(result.points) points")
                .font(.title.bold().monospacedDigit())
                .foregroundStyle(.orange)
            if result.milestoneBonus > 0 {
                Label("Includes a +\(result.milestoneBonus) milestone bonus!", systemImage: "trophy.fill")
                    .foregroundStyle(.yellow)
            }
            Button("Awesome") { dismiss() }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.top)
        }
        .padding(32)
        .presentationDetents([.medium])
    }
}

extension DayStatus {
    var symbol: String {
        switch self {
        case .early: return "checkmark.circle.fill"
        case .late: return "clock.fill"
        case .missed: return "xmark.circle.fill"
        case .off: return "moon.zzz.fill"
        case .pending: return "circle.dashed"
        }
    }

    var color: Color {
        switch self {
        case .early: return .green
        case .late: return .orange
        case .missed: return .red
        case .off: return .secondary
        case .pending: return .secondary
        }
    }

    var label: String {
        switch self {
        case .early: return "Early"
        case .late: return "Late"
        case .missed: return "Missed"
        case .off: return "Day off"
        case .pending: return "Not yet"
        }
    }
}
