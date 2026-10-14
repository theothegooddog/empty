# Early Bird

A SwiftUI iPhone app that tracks your streak of getting to school early and lets you spend the points you earn on rewards like extra screen time or coins in a game.

## What it does

- **Today**: tap **I'm at school!** when you arrive. If it's before the early cutoff (default 10 minutes before an 8:30 bell), your streak grows.
- **Points**: 10 for each early day, plus 2 more for every day in a row (up to +20), plus a bonus every 5th day (+25 at 5, +50 at 10 ... up to +150). Arriving late still earns 2 points but resets the streak.
- **Weekends and days off** never break your streak. Swipe a day in History to mark a holiday or sick day.
- **Rewards**: spend points on screen time, game points, treats or privileges. Bought rewards wait in "Ready to cash in" until a grown-up taps **Used**.
- **Parent code**: an optional 4-digit code locks settings, history edits, adding or deleting rewards, and marking rewards as used.
- **Morning reminder**: an optional notification on school days.

Everything is stored on the phone in a JSON file. Points are recalculated from the check-in history each time, so fixing a past day always keeps the balance right.

## Run it

You need a Mac with Xcode 15 or newer.

**Option A: XcodeGen (quickest)**

```sh
brew install xcodegen
cd EarlyBird
xcodegen
open EarlyBird.xcodeproj
```

**Option B: by hand**

1. In Xcode choose **File > New > Project > iOS App**, name it `EarlyBird`, interface SwiftUI, minimum iOS 17.
2. Delete the generated `ContentView.swift` and `EarlyBirdApp.swift`.
3. Drag the `Sources` folder into the project (tick "Copy items if needed").
4. To run the tests, add `Tests/StreakEngineTests.swift` to the unit-test target.

Then pick a simulator or your iPhone and press Run. On a real device, set your Apple ID team under **Signing & Capabilities**.

## Changing the rules

All the point values live in `PointsRules` in `Sources/StreakEngine.swift`. The starting reward list is `Reward.defaults` in `Sources/Models.swift`.

## Files

| File | What's in it |
| --- | --- |
| `Sources/Models.swift` | Days, check-ins, settings, rewards |
| `Sources/StreakEngine.swift` | Streak and points rules (pure logic, unit tested) |
| `Sources/AppStore.swift` | Saving, check-ins, redeeming, reminders |
| `Sources/Views/` | Today, Rewards, History, Settings screens and the parent code lock |
| `Tests/StreakEngineTests.swift` | Tests for streaks, weekends, days off and points |
