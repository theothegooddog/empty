import CoreLocation
import Foundation
import UserNotifications

@MainActor
final class AppStore: ObservableObject {
    @Published var data: AppData {
        didSet {
            save()
            refresh()
        }
    }
    @Published private(set) var summary: StreakSummary = .empty

    private let fileURL: URL

    init(fileName: String = "earlybird.json") {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        fileURL = docs.appendingPathComponent(fileName)
        if let raw = try? Data(contentsOf: fileURL),
           let decoded = try? JSONDecoder().decode(AppData.self, from: raw) {
            data = decoded
        } else {
            data = AppData()
        }
        refresh()
    }

    // MARK: Derived values

    var spent: Int { data.redemptions.reduce(0) { $0 + $1.cost } }
    var balance: Int { summary.totalEarned - spent }
    var today: Day { Day(Date()) }
    var todayResult: DayResult? { summary.today }
    var isSchoolDayToday: Bool { StreakEngine.isSchoolDay(today, data: data) }
    var unusedRedemptions: [Redemption] { data.redemptions.filter { !$0.used }.sorted { $0.date > $1.date } }

    /// Call when the app comes to the foreground so "today" rolls over at midnight.
    func refresh() {
        summary = StreakEngine.summarize(data)
    }

    // MARK: Check-ins

    /// Records arrival right now. Returns today's result, or nil if already checked in today.
    @discardableResult
    func checkInNow() -> DayResult? {
        let now = Date()
        let day = Day(now)
        guard !data.checkIns.contains(where: { $0.day == day }) else { return nil }
        data.checkIns.append(CheckIn(day: day, arrival: now))
        return summary.results.last(where: { $0.day == day })
    }

    /// Checks the phone is near school before a check-in. Returns nil when it's fine to check in.
    func atSchoolProblem(using permissions: Permissions) async -> CheckInProblem? {
        let s = data.settings
        guard s.requireAtSchool, let lat = s.schoolLatitude, let lon = s.schoolLongitude else { return nil }
        guard permissions.locationAllowed else { return .needsLocationPermission }
        guard let here = await permissions.currentLocation() else { return .locationUnavailable }
        let distance = here.distance(from: CLLocation(latitude: lat, longitude: lon))
        // Give a little slack for GPS accuracy.
        return distance <= s.schoolRadius + here.horizontalAccuracy ? nil : .notAtSchool(meters: Int(distance))
    }

    func setSchoolLocation(_ location: CLLocation) {
        data.settings.schoolLatitude = location.coordinate.latitude
        data.settings.schoolLongitude = location.coordinate.longitude
    }

    func clearSchoolLocation() {
        data.settings.schoolLatitude = nil
        data.settings.schoolLongitude = nil
    }

    /// Adds or replaces the check-in for a past day (for a parent fixing a forgotten tap).
    func setCheckIn(day: Day, arrival: Date) {
        data.checkIns.removeAll { $0.day == day }
        data.checkIns.append(CheckIn(day: day, arrival: arrival))
        data.daysOff.remove(day)
    }

    func removeCheckIn(on day: Day) {
        data.checkIns.removeAll { $0.day == day }
    }

    func toggleDayOff(_ day: Day) {
        if data.daysOff.contains(day) {
            data.daysOff.remove(day)
        } else {
            data.daysOff.insert(day)
        }
    }

    // MARK: Rewards

    func redeem(_ reward: Reward) -> Bool {
        guard balance >= reward.cost else { return false }
        data.redemptions.append(
            Redemption(title: reward.title, cost: reward.cost, category: reward.category, date: Date())
        )
        return true
    }

    func markUsed(_ redemption: Redemption) {
        guard let i = data.redemptions.firstIndex(where: { $0.id == redemption.id }) else { return }
        data.redemptions[i].used = true
    }

    func addReward(_ reward: Reward) {
        data.rewards.append(reward)
    }

    func deleteRewards(at offsets: IndexSet) {
        data.rewards.remove(atOffsets: offsets)
    }

    func resetEverything() {
        let settings = data.settings
        data = AppData()
        data.settings = settings
    }

    // MARK: Persistence

    private func save() {
        do {
            let raw = try JSONEncoder().encode(data)
            try raw.write(to: fileURL, options: .atomic)
        } catch {
            print("EarlyBird: could not save data: \(error)")
        }
    }
}

enum CheckInProblem: Equatable {
    case needsLocationPermission
    case locationUnavailable
    case notAtSchool(meters: Int)

    var title: String {
        switch self {
        case .needsLocationPermission: return "Location is off"
        case .locationUnavailable: return "Can't find you"
        case .notAtSchool: return "Not at school yet"
        }
    }

    var message: String {
        switch self {
        case .needsLocationPermission:
            return "Early Bird needs your location to check that you're at school. Turn it on in Settings."
        case .locationUnavailable:
            return "Your location couldn't be found. Step outside or wait a moment, then try again."
        case .notAtSchool(let meters):
            let distance = meters >= 1000 ? String(format: "%.1f km", Double(meters) / 1000) : "\(meters) m"
            return "You're about \(distance) from school. Tap again once you get there."
        }
    }
}

enum Reminders {
    private static let prefix = "earlybird.morning."

    /// Schedules a repeating morning nudge on each school day, or clears it when reminders are off.
    static func update(for settings: Settings) {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: (1...7).map { prefix + String($0) })
        guard settings.reminderEnabled else { return }

        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = "Beat the bell!"
            let bell = String(format: "%d:%02d", settings.schoolStartHour, settings.schoolStartMinute)
            content.body = "Get to school \(settings.earlyMinutes) min before \(bell) to keep your streak going."
            content.sound = .default

            for weekday in settings.schoolDays {
                var when = DateComponents()
                when.weekday = weekday
                when.hour = settings.reminderHour
                when.minute = settings.reminderMinute
                let trigger = UNCalendarNotificationTrigger(dateMatching: when, repeats: true)
                center.add(UNNotificationRequest(identifier: prefix + String(weekday), content: content, trigger: trigger))
            }
        }
    }
}
