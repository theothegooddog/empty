package com.homeworkbreak;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Base64;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executors;

/**
 * A tiny web server on this computer only (127.0.0.1). The browser page uses it to
 * send scanned questions into the game and to show the answers for printing.
 */
public final class HomeworkServer {
	private static final int MAX_BODY_BYTES = 25 * 1024 * 1024;
	private static HttpServer server;

	private HomeworkServer() {}

	public static void start() {
		try {
			server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), HomeworkConfig.webPort), 0);
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not start the homework web page on port {}", HomeworkConfig.webPort, e);
			server = null;
			return;
		}
		server.setExecutor(Executors.newSingleThreadExecutor(r -> {
			Thread t = new Thread(r, "Homework Break web page");
			t.setDaemon(true);
			return t;
		}));
		server.createContext("/", HomeworkServer::handle);
		server.start();
		HomeworkBreakClient.LOGGER.info("Homework page running at {}", url(""));
	}

	public static boolean isRunning() {
		return server != null;
	}

	public static String url(String path) {
		return "http://localhost:" + HomeworkConfig.webPort + "/" + path;
	}

	private static void handle(HttpExchange ex) throws IOException {
		try (ex) {
			if (!isTrustedRequest(ex)) {
				send(ex, 403, "text/plain", "Forbidden".getBytes(StandardCharsets.UTF_8));
				return;
			}
			String path = ex.getRequestURI().getPath();
			String method = ex.getRequestMethod();

			if (method.equals("GET")) {
				switch (path) {
					case "/", "/scan" -> sendPage(ex, "scan.html");
					case "/print" -> sendPage(ex, "print.html");
					case "/api/homework" -> sendJson(ex, HomeworkStore.toJson());
					default -> {
						if (path.startsWith("/scans/")) {
							sendScanImage(ex, path.substring("/scans/".length()));
						} else {
							send(ex, 404, "text/plain", "Not found".getBytes(StandardCharsets.UTF_8));
						}
					}
				}
				return;
			}

			if (method.equals("POST")) {
				JsonObject body = JsonParser.parseString(readBody(ex)).getAsJsonObject();
				switch (path) {
					case "/api/scan" -> addScan(body);
					case "/api/question" -> updateQuestion(body);
					case "/api/clear" -> HomeworkStore.clearAll();
					default -> {
						send(ex, 404, "text/plain", "Not found".getBytes(StandardCharsets.UTF_8));
						return;
					}
				}
				sendJson(ex, HomeworkStore.toJson());
				return;
			}

			send(ex, 405, "text/plain", "Method not allowed".getBytes(StandardCharsets.UTF_8));
		} catch (Exception e) {
			HomeworkBreakClient.LOGGER.error("Homework page request failed", e);
			try {
				send(ex, 400, "text/plain", ("Error: " + e.getMessage()).getBytes(StandardCharsets.UTF_8));
			} catch (IOException ignored) {
				// Response already started; nothing more we can do.
			}
		}
	}

	/** Only answer pages loaded from this server, so other websites can't mess with your homework. */
	private static boolean isTrustedRequest(HttpExchange ex) {
		String host = ex.getRequestHeaders().getFirst("Host");
		Set<String> allowedHosts = Set.of("localhost:" + HomeworkConfig.webPort, "127.0.0.1:" + HomeworkConfig.webPort);
		if (host == null || !allowedHosts.contains(host)) {
			return false;
		}
		if (ex.getRequestMethod().equals("POST")) {
			String origin = ex.getRequestHeaders().getFirst("Origin");
			return origin == null || origin.equals("http://" + host);
		}
		return true;
	}

	private static void addScan(JsonObject body) throws IOException {
		String scanId = null;
		if (body.has("image") && !body.get("image").isJsonNull()) {
			String file = saveImage(body.get("image").getAsString(), "jpeg", ".jpg");
			scanId = HomeworkStore.addScan(file, body.get("width").getAsInt(), body.get("height").getAsInt()).id;
		}
		JsonArray questions = body.getAsJsonArray("questions");
		for (JsonElement el : questions) {
			JsonObject q = el.getAsJsonObject();
			String text = q.get("text").getAsString().strip();
			String picture = null;
			if (q.has("image") && !q.get("image").isJsonNull()) {
				picture = saveImage(q.get("image").getAsString(), "png", ".png");
			}
			if (text.isEmpty() && picture == null) {
				continue;
			}
			double[] box = null;
			if (scanId != null && q.has("box") && q.get("box").isJsonArray()) {
				JsonArray b = q.getAsJsonArray("box");
				box = new double[] {b.get(0).getAsDouble(), b.get(1).getAsDouble(), b.get(2).getAsDouble(), b.get(3).getAsDouble()};
			}
			HomeworkStore.addQuestion(text, box == null ? null : scanId, box, picture);
		}
	}

	/** Saves a data: URL image into the scans folder and returns its new file name. */
	private static String saveImage(String dataUrl, String type, String extension) throws IOException {
		String prefix = "data:image/" + type + ";base64,";
		if (!dataUrl.startsWith(prefix)) {
			throw new IllegalArgumentException("Picture must be a " + type.toUpperCase());
		}
		byte[] bytes = Base64.getDecoder().decode(dataUrl.substring(prefix.length()));
		String file = UUID.randomUUID() + extension;
		Files.write(HomeworkConfig.SCANS_DIR.resolve(file), bytes);
		return file;
	}

	private static void updateQuestion(JsonObject body) {
		String id = body.get("id").getAsString();
		switch (body.get("action").getAsString()) {
			case "delete" -> HomeworkStore.deleteQuestion(id);
			case "reopen" -> HomeworkStore.reopen(id);
			case "move" -> HomeworkStore.moveAnswer(id, body.get("x").getAsDouble(), body.get("y").getAsDouble());
			case "edit" -> HomeworkStore.editText(id, body.get("text").getAsString());
			default -> throw new IllegalArgumentException("Unknown action");
		}
	}

	private static void sendScanImage(HttpExchange ex, String file) throws IOException {
		// Only serve files the store knows about, so the path can't point anywhere else.
		if (!HomeworkStore.isKnownFile(file)) {
			send(ex, 404, "text/plain", "Not found".getBytes(StandardCharsets.UTF_8));
			return;
		}
		String type = file.endsWith(".png") ? "image/png" : "image/jpeg";
		send(ex, 200, type, Files.readAllBytes(HomeworkConfig.SCANS_DIR.resolve(file)));
	}

	private static void sendPage(HttpExchange ex, String name) throws IOException {
		try (InputStream in = HomeworkServer.class.getResourceAsStream("/assets/homeworkbreak/web/" + name)) {
			if (in == null) {
				send(ex, 404, "text/plain", "Missing page".getBytes(StandardCharsets.UTF_8));
				return;
			}
			send(ex, 200, "text/html; charset=utf-8", in.readAllBytes());
		}
	}

	private static void sendJson(HttpExchange ex, String json) throws IOException {
		send(ex, 200, "application/json; charset=utf-8", json.getBytes(StandardCharsets.UTF_8));
	}

	private static void send(HttpExchange ex, int status, String type, byte[] bytes) throws IOException {
		ex.getResponseHeaders().set("Content-Type", type);
		ex.getResponseHeaders().set("Cache-Control", "no-store");
		ex.sendResponseHeaders(status, bytes.length);
		try (OutputStream out = ex.getResponseBody()) {
			out.write(bytes);
		}
	}

	private static String readBody(HttpExchange ex) throws IOException {
		try (InputStream in = ex.getRequestBody()) {
			byte[] bytes = in.readNBytes(MAX_BODY_BYTES + 1);
			if (bytes.length > MAX_BODY_BYTES) {
				throw new IOException("Upload too big");
			}
			return new String(bytes, StandardCharsets.UTF_8);
		}
	}
}
