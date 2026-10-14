import XCTest
@testable import EarlyBird

final class StreakEngineTests: XCTestCase {
    private var calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "America/Toronto")!
        return c
    }()

    // Monday 2026-10-05 ... Friday 2026-10-09, weekend, Monday 2026-10-12.
    private let monday = Day(year: 2026, month: 10, day: 5)

    private func data(_ arrivals: [(Day, Int, Int)]) -> AppData {
        var d = AppData() // bell 8:30, early = by 8:20, Mon-Fri
        d.checkIns = arrivals.map { CheckIn(day: $0.0, arrival: $0.0.at(hour: $0.1, minute: $0.2, calendar: calendar)) }
        return d
    }

    private func now(_ day: Day, _ hour: Int = 18) -> Date {
        day.at(hour: hour, minute: 0, calendar: calendar)
    }

    func testEarlyCutoffIsInclusive() {
        let s = Settings()
        XCTAssertTrue(StreakEngine.isEarly(monday.at(hour: 8, minute: 20, calendar: calendar), on: monday, settings: s, calendar: calendar))
        XCTAssertFalse(StreakEngine.isEarly(monday.at(hour: 8, minute: 21, calendar: calendar), on: monday, settings: s, calendar: calendar))
    }

    func testStreakGrowsAndPointsEscalate() {
        let days = (0..<3).map { monday.adding(days: $0, calendar: calendar) }
        let summary = StreakEngine.summarize(data(days.map { ($0, 8, 0) }), now: now(days[2]), calendar: calendar)
        XCTAssertEqual(summary.current, 3)
        XCTAssertEqual(summary.results.map(\.points), [10, 12, 14])
        XCTAssertEqual(summary.totalEarned, 36)
    }

    func testWeekendDoesNotBreakStreak() {
        let weekdays = (0..<5).map { monday.adding(days: $0, calendar: calendar) }
        let nextMonday = monday.adding(days: 7, calendar: calendar)
        let summary = StreakEngine.summarize(
            data((weekdays + [nextMonday]).map { ($0, 8, 5) }), now: now(nextMonday), calendar: calendar
        )
        XCTAssertEqual(summary.current, 6)
        XCTAssertEqual(summary.results.filter { $0.status == .off }.count, 2)
    }

    func testFifthDayPaysMilestoneBonus() {
        let weekdays = (0..<5).map { monday.adding(days: $0, calendar: calendar) }
        let summary = StreakEngine.summarize(data(weekdays.map { ($0, 8, 0) }), now: now(weekdays[4]), calendar: calendar)
        let friday = summary.results.last!
        XCTAssertEqual(friday.milestoneBonus, 25)
        XCTAssertEqual(friday.points, 18 + 25)
    }

    func testLateArrivalResetsStreakButEarnsPoints() {
        let tue = monday.adding(days: 1, calendar: calendar)
        let summary = StreakEngine.summarize(data([(monday, 8, 0), (tue, 8, 25)]), now: now(tue), calendar: calendar)
        XCTAssertEqual(summary.current, 0)
        XCTAssertEqual(summary.best, 1)
        XCTAssertEqual(summary.results.last?.status, .late)
        XCTAssertEqual(summary.results.last?.points, PointsRules.latePoints)
    }

    func testMissedSchoolDayResetsStreak() {
        let wed = monday.adding(days: 2, calendar: calendar)
        let summary = StreakEngine.summarize(data([(monday, 8, 0), (wed, 8, 0)]), now: now(wed), calendar: calendar)
        XCTAssertEqual(summary.results[1].status, .missed)
        XCTAssertEqual(summary.current, 1)
    }

    func testDayOffDoesNotBreakStreak() {
        let tue = monday.adding(days: 1, calendar: calendar)
        let wed = monday.adding(days: 2, calendar: calendar)
        var d = data([(monday, 8, 0), (wed, 8, 0)])
        d.daysOff = [tue]
        let summary = StreakEngine.summarize(d, now: now(wed), calendar: calendar)
        XCTAssertEqual(summary.current, 2)
    }

    func testTodayPendingKeepsStreakAlive() {
        let tue = monday.adding(days: 1, calendar: calendar)
        let summary = StreakEngine.summarize(data([(monday, 8, 0)]), now: now(tue, 7), calendar: calendar)
        XCTAssertEqual(summary.today?.status, .pending)
        XCTAssertEqual(summary.current, 1)
    }

    func testEarliestCheckInOfTheDayWins() {
        let summary = StreakEngine.summarize(data([(monday, 8, 25), (monday, 8, 0)]), now: now(monday), calendar: calendar)
        XCTAssertEqual(summary.today?.status, .early)
    }

    func testEmptyHistory() {
        let summary = StreakEngine.summarize(AppData(), now: now(monday), calendar: calendar)
        XCTAssertEqual(summary.current, 0)
        XCTAssertEqual(summary.today?.status, .pending)
    }

    func testMilestoneSchedule() {
        XCTAssertEqual(PointsRules.milestoneBonus(streak: 4), 0)
        XCTAssertEqual(PointsRules.milestoneBonus(streak: 10), 50)
        XCTAssertEqual(PointsRules.milestoneBonus(streak: 60), 150)
        XCTAssertEqual(PointsRules.nextMilestone(after: 0), 5)
        XCTAssertEqual(PointsRules.nextMilestone(after: 5), 10)
        XCTAssertEqual(PointsRules.earlyPoints(streak: 50), 30)
    }

    func testOlderSavedDataStillLoads() throws {
        // Saved before school location and onboarding existed.
        let json = #"{"settings":{"schoolStartHour":9,"schoolStartMinute":0,"earlyMinutes":5,"schoolDays":[2,3,4,5,6],"reminderEnabled":false,"reminderHour":7,"reminderMinute":0},"checkIns":[],"daysOff":[],"rewards":[],"redemptions":[]}"#
        let data = try JSONDecoder().decode(AppData.self, from: Data(json.utf8))
        XCTAssertEqual(data.settings.schoolStartHour, 9)
        XCTAssertFalse(data.settings.hasSchoolLocation)
        XCTAssertEqual(data.settings.schoolRadius, 250)
        XCTAssertTrue(data.hasOnboarded)
        XCTAssertFalse(AppData().hasOnboarded)
    }
}
