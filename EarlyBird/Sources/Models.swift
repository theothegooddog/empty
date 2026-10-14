import Foundation

/// A calendar day with no time attached ("2026-10-14"), so streak math never trips over time zones or DST.
struct Day: Codable, Hashable, Comparable, Identifiable {
    var year: Int
    var month: Int
    var day: Int

    var id: String { String(format: "%04d-%02d-%02d", year, month, day) }

    init(year: Int, month: Int, day: Int) {
        self.year = year
        self.month = month
        self.day = day
    }

    init(_ date: Date, calendar: Calendar = .current) {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        self.init(year: c.year!, month: c.month!, day: c.day!)
    }

    /// Noon on this day. Noon keeps day arithmetic safe across daylight-saving changes.
    func noon(calendar: Calendar = .current) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: 12))!
    }

    func adding(days n: Int, calendar: Calendar = .current) -> Day {
        Day(calendar.date(byAdding: .day, value: n, to: noon(calendar: calendar))!, calendar: calendar)
    }

    /// 1 = Sunday ... 7 = Saturday, matching `Calendar.component(.weekday, ...)`.
    func weekday(calendar: Calendar = .current) -> Int {
        calendar.component(.weekday, from: noon(calendar: calendar))
    }

    /// A time of day (e.g. 8:30) on this day.
    func at(hour: Int, minute: Int, calendar: Calendar = .current) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute))!
    }

    static func < (lhs: Day, rhs: Day) -> Bool {
        (lhs.year, lhs.month, lhs.day) < (rhs.year, rhs.month, rhs.day)
    }
}

struct CheckIn: Codable, Identifiable, Hashable {
    var id = UUID()
    var day: Day
    var arrival: Date
}

struct Settings: Codable, Hashable {
    /// When the first bell rings.
    var schoolStartHour = 8
    var schoolStartMinute = 30
    /// How many minutes before the bell counts as "early".
    var earlyMinutes = 10
    /// Weekdays with school, 1 = Sunday ... 7 = Saturday. Default is Monday to Friday.
    var schoolDays: Set<Int> = [2, 3, 4, 5, 6]

    var reminderEnabled = false
    var reminderHour = 7
    var reminderMinute = 0

    /// Optional 4-digit code a parent sets to lock settings, history edits and new rewards.
    var parentPIN: String? = nil
}

enum RewardCategory: String, Codable, CaseIterable, Identifiable {
    case screenTime, game, treat, privilege

    var id: String { rawValue }

    var label: String {
        switch self {
        case .screenTime: return "Screen time"
        case .game: return "Game points"
        case .treat: return "Treat"
        case .privilege: return "Privilege"
        }
    }

    var symbol: String {
        switch self {
        case .screenTime: return "iphone"
        case .game: return "gamecontroller.fill"
        case .treat: return "birthday.cake.fill"
        case .privilege: return "star.fill"
        }
    }
}

struct Reward: Codable, Identifiable, Hashable {
    var id = UUID()
    var title: String
    var cost: Int
    var category: RewardCategory

    static let defaults: [Reward] = [
        Reward(title: "15 min extra screen time", cost: 40, category: .screenTime),
        Reward(title: "30 min extra screen time", cost: 75, category: .screenTime),
        Reward(title: "500 coins in my game", cost: 60, category: .game),
        Reward(title: "Unlock a new game level or skin", cost: 120, category: .game),
        Reward(title: "Pick a snack at the store", cost: 50, category: .treat),
        Reward(title: "Choose what's for dinner", cost: 150, category: .privilege),
        Reward(title: "Stay up 30 min later on Friday", cost: 200, category: .privilege),
    ]
}

/// A reward the kid has bought with points. It stays "unused" until a parent hands it over.
struct Redemption: Codable, Identifiable, Hashable {
    var id = UUID()
    var title: String
    var cost: Int
    var category: RewardCategory
    var date: Date
    var used = false
}

struct AppData: Codable, Hashable {
    var settings = Settings()
    var checkIns: [CheckIn] = []
    /// Holidays, sick days and snow days. They neither count toward nor break the streak.
    var daysOff: Set<Day> = []
    var rewards: [Reward] = Reward.defaults
    var redemptions: [Redemption] = []
}
