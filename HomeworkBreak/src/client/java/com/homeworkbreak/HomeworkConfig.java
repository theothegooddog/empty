package com.homeworkbreak;

import net.fabricmc.loader.api.FabricLoader;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

/**
 * Everything lives in .minecraft/config/homeworkbreak/:
 *   settings.properties - how often breaks happen, how long you must stay on a question, web page port
 *   questions.txt       - optional: type questions here, one per line (lines starting with # are ignored)
 *   homework.json       - every question, your answers and drawings (managed by the mod)
 *   scans/              - photos of your homework from the webcam
 */
public final class HomeworkConfig {
	public static final Path DIR = FabricLoader.getInstance().getConfigDir().resolve("homeworkbreak");
	public static final Path QUESTIONS_TXT = DIR.resolve("questions.txt");
	public static final Path HOMEWORK_JSON = DIR.resolve("homework.json");
	public static final Path SCANS_DIR = DIR.resolve("scans");
	private static final Path SETTINGS = DIR.resolve("settings.properties");

	public static int minMinutes = 10;
	public static int maxMinutes = 20;
	public static int minSecondsPerQuestion = 60;
	public static int webPort = 25599;

	private HomeworkConfig() {}

	public static void load() {
		try {
			Files.createDirectories(SCANS_DIR);
			if (Files.notExists(QUESTIONS_TXT)) {
				Files.writeString(QUESTIONS_TXT, """
						# The easiest way to add homework is to scan it with your webcam:
						# type /homework in Minecraft, or press the "Homework" button on the pause menu.
						#
						# You can also type questions here, one per line. Lines that start with # are ignored.
						""", StandardCharsets.UTF_8);
			}

			Properties p = new Properties();
			if (Files.exists(SETTINGS)) {
				try (Reader r = Files.newBufferedReader(SETTINGS, StandardCharsets.UTF_8)) {
					p.load(r);
				}
			}
			minMinutes = Math.max(1, readInt(p, "min_minutes_between_questions", minMinutes));
			maxMinutes = Math.max(minMinutes, readInt(p, "max_minutes_between_questions", maxMinutes));
			minSecondsPerQuestion = Math.max(0, readInt(p, "min_seconds_on_each_question", minSecondsPerQuestion));
			webPort = readInt(p, "web_page_port", webPort);

			// Write the file back so any newly added settings show up in it.
			p.setProperty("min_minutes_between_questions", String.valueOf(minMinutes));
			p.setProperty("max_minutes_between_questions", String.valueOf(maxMinutes));
			p.setProperty("min_seconds_on_each_question", String.valueOf(minSecondsPerQuestion));
			p.setProperty("web_page_port", String.valueOf(webPort));
			try (Writer w = Files.newBufferedWriter(SETTINGS, StandardCharsets.UTF_8)) {
				p.store(w, "Homework Break settings (restart the game after changing)");
			}
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not load Homework Break settings", e);
		}
	}

	private static int readInt(Properties p, String key, int fallback) {
		try {
			return Integer.parseInt(p.getProperty(key, "").trim());
		} catch (NumberFormatException e) {
			return fallback;
		}
	}
}
