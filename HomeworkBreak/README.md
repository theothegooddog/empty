# Homework Break (Minecraft 26.2, Fabric)

Every 10–20 minutes of playing, this mod pauses the game and gives you the next
question from your homework. You type your answer in a box and can work it out
in a drawing area next to it. Once you're done, you can print your homework
sheet with all your answers written on it.

## Install

1. Install [Fabric Loader](https://fabricmc.net/use/installer/) for Minecraft **26.2**.
2. Put these in your `.minecraft/mods` folder:
   - `dist/homeworkbreak-2.1.0.jar` from this folder
   - [Fabric API](https://modrinth.com/mod/fabric-api) for 26.2
3. Launch Minecraft with the Fabric profile.

## 1. Take a picture of your homework

Press **Esc** in game and click the **Homework** button in the top-left corner
(or type `/homework` in chat). Your browser opens the homework page.

1. Click **Start webcam**, hold your homework sheet up to the camera, and click
   **Take picture**. (Or click **Upload a photo** to use a picture from your phone.)
2. Click **Crop to the paper** and drag a box around the sheet, so the printout
   is just your homework.
3. **Drag a box around each question** on the photo. Each box becomes one
   homework break, and the game shows that part of the photo. If you don't draw
   any boxes, the whole page becomes one question. You can also type questions in.
4. Click **Send to Minecraft**.

The page only works on your own computer while Minecraft is running. It doesn't
need the internet.

## 2. Answer questions while you play

When a homework break pops up:

- **Left side:** the picture of the question (click it to make it bigger),
  plus a box to type your answer.
- **Right side:** a drawing area for working things out with your mouse.
  **Undo** removes the last line and **Clear drawing** wipes it.
- The **Done** button unlocks after a minute, once you've typed an answer.
  Esc won't close it.

Want to do one right now? Type `/homework now`.

## 3. Print your answers

Type `/homework print` (or click **Answers & Print** on the homework page).
The photo of your sheet shows your typed answers and drawings under each question.
Drag any answer to move it if it's in the wrong spot, then click **Print**.

The **All questions** list at the bottom lets you delete questions or make a
finished one come back again ("Ask again").

## Settings

`.minecraft/config/homeworkbreak/settings.properties` (restart the game after changing):

| Setting | Default | Meaning |
|---|---|---|
| `min_minutes_between_questions` | 10 | Shortest gap between breaks |
| `max_minutes_between_questions` | 20 | Longest gap between breaks |
| `min_seconds_on_each_question` | 60 | How long before the Done button unlocks |
| `web_page_port` | 25599 | Port for the homework page; change it if something else uses 25599 |

You can still type questions into `config/homeworkbreak/questions.txt`
(one per line) instead of scanning. Everything you've done is saved in
`config/homeworkbreak/homework.json` and the photos in `config/homeworkbreak/scans/`.

Only time spent actually playing counts (time in menus doesn't). In
singleplayer the game is paused during a break. On a multiplayer server the
game can't be paused, but the question still covers your screen.

## Build it yourself

Needs Java 25: `./gradlew build`, then the jar is in `build/libs/`.
