# Homework Break (Minecraft 26.2, Fabric)

Every 10–20 minutes of playing, this mod pauses the game and shows you the next
question from your homework. You work it out and write the answer on your
homework paper. After a minute, the **"I wrote it on my paper ✓"** button
unlocks and you can keep playing. Esc won't close it.

## Install

1. Install [Fabric Loader](https://fabricmc.net/use/installer/) for Minecraft **26.2**.
2. Put these in your `.minecraft/mods` folder:
   - `dist/homeworkbreak-1.0.0.jar` from this folder
   - [Fabric API](https://modrinth.com/mod/fabric-api) for 26.2
3. Launch Minecraft with the Fabric profile once. That creates the config folder.

## Add your homework

Open `.minecraft/config/homeworkbreak/questions.txt` and put one question per line:

```
Solve for x: 3x + 5 = 20
Page 42, question 7
Write one sentence using the word "enormous".
```

Lines starting with `#` are ignored. Delete the two example lines. You can
edit this file while the game is running; it's re-read at every break.

Questions come up in order. Once you've done them all, the breaks stop.
To start over with a new list, delete `progress.txt` in the same folder.

## Settings

`.minecraft/config/homeworkbreak/settings.properties` (restart the game after changing):

| Setting | Default | Meaning |
|---|---|---|
| `min_minutes_between_questions` | 10 | Shortest gap between breaks |
| `max_minutes_between_questions` | 20 | Longest gap between breaks |
| `min_seconds_on_each_question` | 60 | How long before the "done" button unlocks |

Only time spent actually playing counts (time in menus doesn't). In
singleplayer the game is paused during a break. On a multiplayer server the
game can't be paused, but the question still covers your screen.

## Build it yourself

Needs Java 25: `./gradlew build`, then the jar is in `build/libs/`.
