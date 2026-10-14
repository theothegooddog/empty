# Early Bird

A SwiftUI iPhone app that tracks your streak of getting to school early and lets you spend the points you earn on rewards like extra screen time or coins in a game.

## What it does

- **Today**: tap **I'm at school!** when you arrive. If it's before the early cutoff (default 10 minutes before an 8:30 bell), your streak grows.
- **Points**: 10 for each early day, plus 2 more for every day in a row (up to +20), plus a bonus every 5th day (+25 at 5, +50 at 10 ... up to +150). Arriving late still earns 2 points but resets the streak.
- **Weekends and days off** never break your streak. Swipe a day in History to mark a holiday or sick day.
- **Rewards**: spend points on screen time, game points, treats or privileges. Bought rewards wait in "Ready to cash in" until a grown-up taps **Used**.
- **Parent code**: an optional 4-digit code locks settings, history edits, adding or deleting rewards, and marking rewards as used.
- **Morning reminder**: an optional notification on school days.
- **At-school check**: save your school's spot once, and "I'm at school!" only works when you're actually there.
- **Permissions**: on first launch a short setup asks for notification permission (reminders) and location permission (the at-school check). Settings shows each permission's status, with a button to ask again or open the Settings app if you said no. Location is only read when you tap the check-in button.

Everything is stored on the phone in a JSON file. Points are recalculated from the check-in history each time, so fixing a past day always keeps the balance right.

## Run it

`EarlyBird.swiftpm` is a Swift Playgrounds app package.

**On an iPad or Mac with Swift Playgrounds (4.4 or newer)**
1. Copy the `EarlyBird.swiftpm` folder to the iPad or Mac (AirDrop, iCloud Drive or the Files app all work).
2. Open it in Swift Playgrounds and tap **Run**.

**On a Mac with Xcode 15 or newer**
1. Double-click `EarlyBird.swiftpm` (or **File > Open** it in Xcode).
2. Pick a simulator or your iPhone and press Run. On a real iPhone, choose your Apple ID team under **Signing & Capabilities**.

In the Simulator you can fake a location with **Features > Location** to try the at-school check.

**Running the unit tests (optional)**

The tests live outside the app package, because Swift Playgrounds doesn't run tests. To run them, generate a regular Xcode project with XcodeGen:

```sh
brew install xcodegen
cd EarlyBird
xcodegen
open EarlyBird.xcodeproj   # then Product > Test
```

## Changing the rules

All the point values live in `PointsRules` in `EarlyBird.swiftpm/StreakEngine.swift`. The starting reward list is `Reward.defaults` in `EarlyBird.swiftpm/Models.swift`.

## Files

| File | What's in it |
| --- | --- |
| `EarlyBird.swiftpm/Package.swift` | App package: name, icon, accent color, location permission text |
| `EarlyBird.swiftpm/Models.swift` | Days, check-ins, settings, rewards |
| `EarlyBird.swiftpm/StreakEngine.swift` | Streak and points rules (pure logic, unit tested) |
| `EarlyBird.swiftpm/AppStore.swift` | Saving, check-ins, at-school check, redeeming, reminders |
| `EarlyBird.swiftpm/Permissions.swift` | Asking for and tracking notification and location permission |
| `EarlyBird.swiftpm/Views/` | Setup, Today, Rewards, History, Settings screens and the parent code lock |
| `Tests/StreakEngineTests.swift` | Tests for streaks, weekends, days off and points |
