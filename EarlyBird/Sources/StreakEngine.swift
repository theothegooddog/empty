import Foundation

enum DayStatus: Equatable {
    /// Arrived early: the streak grows.
    case early
    /// Showed up, but not early enough: the streak resets.
    case late
    /// School day with no check-in: the streak resets.
    case missed
    /// Weekend, holiday or other day off: the streak is untouched.
    case off
    /// Today, not checked in yet: the streak is still alive.
    case pending
}

struct DayResult: Identifiable, Equatable {
    var day: Day
    var status: DayStatus
    var arrival: Date?
    /// Streak length at the end of this day.
    var streak: Int
    var points: Int
    /// Bonus included in `points` for hitting a milestone, or 0.
    var milestoneBonus: Int

    var id: Day { day }
}

struct StreakSummary: Equatable {
    var results: [DayResult] = []
    var current = 0
    var best = 0
    var totalEarned = 0

    var today: DayResult? { results.last }

    static let empty = StreakSummary()
}

/// How points are earned. Tweak these numbers to rebalance the game.
enum PointsRules {
    static let earlyBase = 10
    static let bonusPerStreakDay = 2
    static let maxStreakBonus = 20
    static let latePoints = 2
    static let milestoneEvery = 5
    static let maxMilestoneBonus = 150

    /// Every 5th day in a row pays a bonus: 25 at 5 days, 50 at 10, 75 at 15 ... up to 150.
    static func milestoneBonus(streak: Int) -> Int {
        guard streak > 0, streak % milestoneEvery == 0 else { return 0 }
        return min(streak * 5, maxMilestoneBonus)
    }

    /// Points for one early arrival, not counting a milestone bonus.
    /// Day 1 pays 10, day 2 pays 12, day 3 pays 14 ... capped at 30.
    static func earlyPoints(streak: Int) -> Int {
        earlyBase + min(max(streak - 1, 0) * bonusPerStreakDay, maxStreakBonus)
    }

    static func nextMilestone(after streak: Int) -> Int {
        (streak / milestoneEvery + 1) * milestoneEvery
    }
}

enum StreakEngine {
    static func isSchoolDay(_ day: Day, data: AppData, calendar: Calendar = .current) -> Bool {
        data.settings.schoolDays.contains(day.weekday(calendar: calendar)) && !data.daysOff.contains(day)
    }

    static func bellTime(on day: Day, settings: Settings, calendar: Calendar = .current) -> Date {
        day.at(hour: settings.schoolStartHour, minute: settings.schoolStartMinute, calendar: calendar)
    }

    /// The latest arrival that still counts as early.
    static func earlyDeadline(on day: Day, settings: Settings, calendar: Calendar = .current) -> Date {
        bellTime(on: day, settings: settings, calendar: calendar)
            .addingTimeInterval(-Double(settings.earlyMinutes * 60))
    }

    static func isEarly(_ arrival: Date, on day: Day, settings: Settings, calendar: Calendar = .current) -> Bool {
        arrival <= earlyDeadline(on: day, settings: settings, calendar: calendar)
    }

    /// Minutes before the bell (negative means after the bell).
    static func minutesBeforeBell(_ arrival: Date, on day: Day, settings: Settings, calendar: Calendar = .current) -> Int {
        Int(bellTime(on: day, settings: settings, calendar: calendar).timeIntervalSince(arrival) / 60)
    }

    /// Replays the whole history from the first check-in to today.
    /// Points are derived from history rather than stored, so fixing a past day always keeps the balance correct.
    static func summarize(_ data: AppData, now: Date = Date(), calendar: Calendar = .current) -> StreakSummary {
        let today = Day(now, calendar: calendar)

        // Keep only the earliest check-in for each day.
        var firstByDay: [Day: CheckIn] = [:]
        for checkIn in data.checkIns {
            if let existing = firstByDay[checkIn.day], existing.arrival <= checkIn.arrival { continue }
            firstByDay[checkIn.day] = checkIn
        }

        guard let first = firstByDay.keys.min(), first <= today else {
            let status: DayStatus = isSchoolDay(today, data: data, calendar: calendar) ? .pending : .off
            return StreakSummary(
                results: [DayResult(day: today, status: status, arrival: nil, streak: 0, points: 0, milestoneBonus: 0)]
            )
        }

        var summary = StreakSummary()
        var running = 0
        var day = first

        while day <= today {
            let arrival = firstByDay[day]?.arrival
            var status: DayStatus
            var points = 0
            var milestone = 0

            if !isSchoolDay(day, data: data, calendar: calendar) {
                status = .off
            } else if let arrival {
                if isEarly(arrival, on: day, settings: data.settings, calendar: calendar) {
                    running += 1
                    status = .early
                    milestone = PointsRules.milestoneBonus(streak: running)
                    points = PointsRules.earlyPoints(streak: running) + milestone
                } else {
                    running = 0
                    status = .late
                    points = PointsRules.latePoints
                }
            } else if day == today {
                status = .pending
            } else {
                running = 0
                status = .missed
            }

            summary.best = max(summary.best, running)
            summary.totalEarned += points
            summary.results.append(
                DayResult(day: day, status: status, arrival: arrival, streak: running, points: points, milestoneBonus: milestone)
            )
            day = day.adding(days: 1, calendar: calendar)
        }

        summary.current = running
        return summary
    }
}
