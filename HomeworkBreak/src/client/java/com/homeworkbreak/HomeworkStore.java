package com.homeworkbreak;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * All homework questions, answers and drawings, saved to homework.json.
 * Used from both the game thread and the web server thread, so every method is synchronized.
 */
public final class HomeworkStore {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

	public static final class Scan {
		public String id;
		public String file;
		public int width;
		public int height;
	}

	public static final class Question {
		public String id;
		public String text;
		/** The photo of the whole sheet this question is on, or null if it was typed in. */
		public String scanId;
		/** Picture of just this question (a PNG in scans/), shown in the game. Null for typed questions. */
		public String image;
		/** Where the question is on the scan photo: x, y, width, height in photo pixels. */
		public double[] box;
		/** Where the answer goes on the scan photo (x, y in photo pixels); null means just under the question. */
		public double[] answerPos;
		public String answer = "";
		/** Each stroke is a flat list x0, y0, x1, y1, ... with coordinates from 0 to 1. */
		public List<List<Float>> strokes = new ArrayList<>();
		/** Width divided by height of the drawing area the strokes were drawn in. */
		public double drawingAspect = 1;
		public boolean done;
	}

	public static final class Data {
		public List<Scan> scans = new ArrayList<>();
		public List<Question> questions = new ArrayList<>();
		public Set<String> importedLines = new LinkedHashSet<>();
		public int nextId = 1;
	}

	private static Data data = new Data();

	private HomeworkStore() {}

	public static synchronized void load() {
		try {
			if (Files.exists(HomeworkConfig.HOMEWORK_JSON)) {
				Data loaded = GSON.fromJson(Files.readString(HomeworkConfig.HOMEWORK_JSON, StandardCharsets.UTF_8), Data.class);
				if (loaded != null) {
					data = loaded;
				}
			}
		} catch (Exception e) {
			HomeworkBreakClient.LOGGER.error("Could not read homework.json", e);
		}
		importQuestionsTxt();
	}

	/** Adds any new lines from questions.txt as questions. */
	public static synchronized void importQuestionsTxt() {
		try {
			boolean changed = false;
			for (String line : Files.readAllLines(HomeworkConfig.QUESTIONS_TXT, StandardCharsets.UTF_8)) {
				String q = line.strip();
				if (!q.isEmpty() && !q.startsWith("#") && data.importedLines.add(q)) {
					addQuestion(q, null, null);
					changed = true;
				}
			}
			if (changed) {
				save();
			}
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not read questions.txt", e);
		}
	}

	public static synchronized String toJson() {
		return GSON.toJson(data);
	}

	public static synchronized Question nextQuestion() {
		for (Question q : data.questions) {
			if (!q.done) {
				return copy(q);
			}
		}
		return null;
	}

	/** Position of a question in the list (1-based) and how many there are in total. */
	public static synchronized int[] positionOf(String id) {
		for (int i = 0; i < data.questions.size(); i++) {
			if (data.questions.get(i).id.equals(id)) {
				return new int[] {i + 1, data.questions.size()};
			}
		}
		return new int[] {0, data.questions.size()};
	}

	public static synchronized int remainingCount() {
		return (int) data.questions.stream().filter(q -> !q.done).count();
	}

	public static synchronized void saveWork(String id, String answer, List<List<Float>> strokes, double aspect, boolean done) {
		Question q = find(id);
		if (q == null) {
			return;
		}
		q.answer = answer;
		q.strokes = new ArrayList<>();
		for (List<Float> s : strokes) {
			q.strokes.add(new ArrayList<>(s));
		}
		q.drawingAspect = aspect;
		q.done = q.done || done;
		save();
	}

	public static synchronized Scan addScan(String file, int width, int height) {
		Scan s = new Scan();
		s.id = "s" + data.nextId++;
		s.file = file;
		s.width = width;
		s.height = height;
		data.scans.add(s);
		save();
		return s;
	}

	public static synchronized Question addQuestion(String text, String scanId, double[] box) {
		return addQuestion(text, scanId, box, null);
	}

	public static synchronized Question addQuestion(String text, String scanId, double[] box, String image) {
		Question q = new Question();
		q.id = "q" + data.nextId++;
		q.text = text;
		q.scanId = scanId;
		q.box = box;
		q.image = image;
		data.questions.add(q);
		save();
		return q;
	}

	public static synchronized boolean deleteQuestion(String id) {
		Question q = find(id);
		if (q != null && q.image != null) {
			deleteFile(q.image);
		}
		boolean removed = data.questions.removeIf(x -> x.id.equals(id));
		save();
		return removed;
	}

	public static synchronized void reopen(String id) {
		Question q = find(id);
		if (q != null) {
			q.done = false;
			save();
		}
	}

	public static synchronized void moveAnswer(String id, double x, double y) {
		Question q = find(id);
		if (q != null) {
			q.answerPos = new double[] {x, y};
			save();
		}
	}

	public static synchronized void editText(String id, String text) {
		Question q = find(id);
		if (q != null) {
			q.text = text;
			save();
		}
	}

	/** True if the file is a sheet photo or question picture this store knows about. */
	public static synchronized boolean isKnownFile(String file) {
		for (Scan s : data.scans) {
			if (s.file.equals(file)) {
				return true;
			}
		}
		for (Question q : data.questions) {
			if (file.equals(q.image)) {
				return true;
			}
		}
		return false;
	}

	public static synchronized void clearAll() {
		Set<String> imported = data.importedLines;
		for (Scan s : data.scans) {
			deleteFile(s.file);
		}
		for (Question q : data.questions) {
			if (q.image != null) {
				deleteFile(q.image);
			}
		}
		data = new Data();
		// Keep remembering lines already taken from questions.txt so they don't all come back.
		data.importedLines = imported;
		save();
	}

	private static void deleteFile(String file) {
		try {
			Files.deleteIfExists(HomeworkConfig.SCANS_DIR.resolve(file));
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.warn("Could not delete {}", file, e);
		}
	}

	private static Question find(String id) {
		for (Question q : data.questions) {
			if (q.id.equals(id)) {
				return q;
			}
		}
		return null;
	}

	private static Question copy(Question q) {
		return GSON.fromJson(GSON.toJson(q), Question.class);
	}

	private static void save() {
		try {
			Path tmp = HomeworkConfig.HOMEWORK_JSON.resolveSibling("homework.json.tmp");
			Files.writeString(tmp, GSON.toJson(data), StandardCharsets.UTF_8);
			Files.move(tmp, HomeworkConfig.HOMEWORK_JSON, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not save homework.json", e);
		}
	}
}
