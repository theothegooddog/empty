package com.homeworkbreak;

import net.fabricmc.loader.api.FabricLoader;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;

/**
 * Everything lives in .minecraft/config/homeworkbreak/:
 *   questions.txt       - one homework question per line (lines starting with # are ignored)
 *   settings.properties - how often breaks happen and how long you must stay on a question
 *   progress.txt        - which question is next (delete it to start over)
 */
public final class HomeworkConfig {
	private static final Path DIR = FabricLoader.getInstance().getConfigDir().resolve("homeworkbreak");
	private static final Path QUESTIONS = DIR.resolve("questions.txt");
	private static final Path SETTINGS = DIR.resolve("settings.properties");
	private static final Path PROGRESS = DIR.resolve("progress.txt");

	public static int minMinutes = 10;
	public static int maxMinutes = 20;
	public static int minSecondsPerQuestion = 60;

	private static List<String> questions = new ArrayList<>();
	private static int nextIndex = 0;

	private HomeworkConfig() {}

	public static void load() {
		try {
			Files.createDirectories(DIR);
			if (Files.notExists(QUESTIONS)) {
				Files.writeString(QUESTIONS, """
						# Put your homework questions here, one per line.
						# Lines that start with # are ignored.
						# Edit this file while the game is running and it will pick up the changes
						# at the next homework break.
						Example: What is 7 x 8?
						Example: Write one sentence using the word "enormous".
						""", StandardCharsets.UTF_8);
			}
			if (Files.notExists(SETTINGS)) {
				Properties defaults = new Properties();
				defaults.setProperty("min_minutes_between_questions", String.valueOf(minMinutes));
				defaults.setProperty("max_minutes_between_questions", String.valueOf(maxMinutes));
				defaults.setProperty("min_seconds_on_each_question", String.valueOf(minSecondsPerQuestion));
				try (Writer w = Files.newBufferedWriter(SETTINGS, StandardCharsets.UTF_8)) {
					defaults.store(w, "Homework Break settings (restart the game after changing)");
				}
			}

			Properties p = new Properties();
			try (Reader r = Files.newBufferedReader(SETTINGS, StandardCharsets.UTF_8)) {
				p.load(r);
			}
			minMinutes = Math.max(1, readInt(p, "min_minutes_between_questions", minMinutes));
			maxMinutes = Math.max(minMinutes, readInt(p, "max_minutes_between_questions", maxMinutes));
			minSecondsPerQuestion = Math.max(0, readInt(p, "min_seconds_on_each_question", minSecondsPerQuestion));

			reloadQuestions();
			if (Files.exists(PROGRESS)) {
				nextIndex = Math.max(0, readIntOr(Files.readString(PROGRESS).trim(), 0));
			}
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not load Homework Break config", e);
		}
	}

	public static void reloadQuestions() {
		try {
			List<String> loaded = new ArrayList<>();
			for (String line : Files.readAllLines(QUESTIONS, StandardCharsets.UTF_8)) {
				String q = line.strip();
				if (!q.isEmpty() && !q.startsWith("#")) {
					loaded.add(q);
				}
			}
			questions = loaded;
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not read questions.txt", e);
		}
	}

	public static int questionCount() {
		return questions.size();
	}

	public static int nextIndex() {
		return nextIndex;
	}

	public static boolean hasNextQuestion() {
		return nextIndex < questions.size();
	}

	public static String nextQuestion() {
		return questions.get(nextIndex);
	}

	public static void markCurrentDone() {
		nextIndex++;
		try {
			Files.writeString(PROGRESS, String.valueOf(nextIndex));
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not save progress", e);
		}
	}

	private static int readInt(Properties p, String key, int fallback) {
		return readIntOr(p.getProperty(key, ""), fallback);
	}

	private static int readIntOr(String s, int fallback) {
		try {
			return Integer.parseInt(s.trim());
		} catch (NumberFormatException e) {
			return fallback;
		}
	}
}
