package com.homeworkbreak;

import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.MultiLineEditBox;
import net.minecraft.client.gui.components.MultiLineTextWidget;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.input.MouseButtonEvent;
import net.minecraft.network.chat.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * The homework break: the question and an answer box on the left, a drawing area for
 * working things out on the right. Can't be closed until the answer is typed in.
 */
public class HomeworkScreen extends Screen {
	private static final int WHITE = 0xFFFFFFFF;
	private static final int YELLOW = 0xFFFFFF55;
	private static final int GRAY = 0xFFAAAAAA;
	private static final int DIM = 0x70000000;
	private static final int PAPER = 0xFFF4F1E8;
	private static final int PAPER_EDGE = 0xFF8A8A8A;
	private static final int INK = 0xFF1A2A6C;

	private static final int MARGIN = 8;
	private static final int TOP = 30;

	private final HomeworkStore.Question question;
	private final int number;
	private final int total;
	private final long unlockAtMillis;

	/** Strokes as flat lists of x, y pairs, each from 0 to 1 across the drawing area. */
	private final List<List<Float>> strokes = new ArrayList<>();
	private List<Float> currentStroke;
	private String answer;

	private MultiLineEditBox answerBox;
	private Button doneButton;
	private boolean finished;

	private int canvasX0, canvasY0, canvasX1, canvasY1;

	public HomeworkScreen(HomeworkStore.Question question, int number, int total, int minSeconds) {
		super(Component.literal("Homework Break!"));
		this.question = question;
		this.number = number;
		this.total = total;
		this.unlockAtMillis = System.currentTimeMillis() + minSeconds * 1000L;
		this.answer = question.answer == null ? "" : question.answer;
		for (List<Float> s : question.strokes) {
			strokes.add(new ArrayList<>(s));
		}
	}

	@Override
	protected void init() {
		int colWidth = (this.width - 2 * MARGIN - MARGIN) / 2;
		int leftX = MARGIN;
		int rightX = MARGIN + colWidth + MARGIN;
		int bottomRowY = this.height - 26;

		MultiLineTextWidget questionText = new MultiLineTextWidget(leftX, TOP, Component.literal(question.text), this.font)
				.setMaxWidth(colWidth);
		addRenderableOnly(questionText);

		int answerTop = TOP + questionText.getHeight() + 16;
		// Leave room under the box for its character counter.
		int answerHeight = Math.max(30, bottomRowY - 16 - answerTop);
		answerBox = MultiLineEditBox.builder()
				.setX(leftX)
				.setY(answerTop)
				.setPlaceholder(Component.literal("Type your answer here..."))
				.build(this.font, colWidth, answerHeight, Component.literal("Your answer"));
		answerBox.setCharacterLimit(2000);
		answerBox.setValue(answer);
		answerBox.setValueListener(v -> answer = v);
		addRenderableWidget(answerBox);
		setInitialFocus(answerBox);

		doneButton = addRenderableWidget(Button.builder(Component.empty(), b -> finish())
				.bounds(leftX, bottomRowY, colWidth, 20)
				.build());

		canvasX0 = rightX;
		canvasY0 = TOP + 10;
		canvasX1 = rightX + colWidth;
		canvasY1 = bottomRowY - 6;

		int half = (colWidth - 4) / 2;
		addRenderableWidget(Button.builder(Component.literal("Undo"), b -> {
			if (!strokes.isEmpty()) {
				strokes.remove(strokes.size() - 1);
			}
		}).bounds(rightX, bottomRowY, half, 20).build());
		addRenderableWidget(Button.builder(Component.literal("Clear drawing"), b -> strokes.clear())
				.bounds(rightX + half + 4, bottomRowY, colWidth - half - 4, 20).build());

		updateButton();
	}

	private int secondsLeft() {
		long ms = unlockAtMillis - System.currentTimeMillis();
		return ms <= 0 ? 0 : (int) ((ms + 999) / 1000);
	}

	private boolean canFinish() {
		return secondsLeft() == 0 && !answer.isBlank();
	}

	private void updateButton() {
		int left = secondsLeft();
		doneButton.active = canFinish();
		if (left > 0) {
			doneButton.setMessage(Component.literal("Keep working... (" + left + "s)"));
		} else if (answer.isBlank()) {
			doneButton.setMessage(Component.literal("Type your answer first"));
		} else {
			doneButton.setMessage(Component.literal("Done ✔"));
		}
	}

	@Override
	public void tick() {
		updateButton();
	}

	private void finish() {
		if (!canFinish()) {
			return;
		}
		finished = true;
		saveWork();
		HomeworkBreakClient.questionFinished();
		this.minecraft.gui.setScreen(null);
	}

	private void saveWork() {
		double aspect = (double) (canvasX1 - canvasX0) / Math.max(1, canvasY1 - canvasY0);
		HomeworkStore.saveWork(question.id, answer, strokes, aspect, finished);
	}

	@Override
	public void removed() {
		// Keep what you've done so far, even if something else interrupts the break.
		saveWork();
		super.removed();
	}

	// --- drawing area ---

	private boolean insideCanvas(double x, double y) {
		return x >= canvasX0 && x < canvasX1 && y >= canvasY0 && y < canvasY1;
	}

	private void addPoint(double x, double y) {
		float nx = (float) Math.clamp((x - canvasX0) / (canvasX1 - canvasX0), 0, 1);
		float ny = (float) Math.clamp((y - canvasY0) / (canvasY1 - canvasY0), 0, 1);
		currentStroke.add(nx);
		currentStroke.add(ny);
	}

	@Override
	public boolean mouseClicked(MouseButtonEvent event, boolean doubleClick) {
		if (event.button() == 0 && insideCanvas(event.x(), event.y())) {
			currentStroke = new ArrayList<>();
			strokes.add(currentStroke);
			addPoint(event.x(), event.y());
			addPoint(event.x(), event.y());
			setFocused(null);
			return true;
		}
		return super.mouseClicked(event, doubleClick);
	}

	@Override
	public boolean mouseDragged(MouseButtonEvent event, double dx, double dy) {
		if (currentStroke != null) {
			addPoint(event.x(), event.y());
			return true;
		}
		return super.mouseDragged(event, dx, dy);
	}

	@Override
	public boolean mouseReleased(MouseButtonEvent event) {
		if (currentStroke != null) {
			currentStroke = null;
			return true;
		}
		return super.mouseReleased(event);
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor g, int mouseX, int mouseY, float partialTick) {
		updateButton();

		g.fill(0, 0, this.width, this.height, DIM);
		g.centeredText(this.font, this.title, this.width / 2, 6, YELLOW);
		g.centeredText(this.font, "Question " + number + " of " + total, this.width / 2, 17, GRAY);

		g.text(this.font, "Working out (draw here):", canvasX0, TOP, WHITE);
		g.fill(canvasX0 - 1, canvasY0 - 1, canvasX1 + 1, canvasY1 + 1, PAPER_EDGE);
		g.fill(canvasX0, canvasY0, canvasX1, canvasY1, PAPER);
		drawStrokes(g);

		g.text(this.font, "Your answer:", answerBox.getX(), answerBox.getY() - 10, WHITE);

		super.extractRenderState(g, mouseX, mouseY, partialTick);
	}

	private void drawStrokes(GuiGraphicsExtractor g) {
		int w = canvasX1 - canvasX0;
		int h = canvasY1 - canvasY0;
		for (List<Float> s : strokes) {
			for (int i = 0; i + 3 < s.size(); i += 2) {
				double x0 = canvasX0 + s.get(i) * w;
				double y0 = canvasY0 + s.get(i + 1) * h;
				double x1 = canvasX0 + s.get(i + 2) * w;
				double y1 = canvasY0 + s.get(i + 3) * h;
				int steps = (int) Math.max(1, Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0))));
				for (int k = 0; k <= steps; k++) {
					int px = (int) Math.round(x0 + (x1 - x0) * k / steps);
					int py = (int) Math.round(y0 + (y1 - y0) * k / steps);
					g.fill(Math.min(px, canvasX1 - 1), Math.min(py, canvasY1 - 1), Math.min(px + 1, canvasX1), Math.min(py + 1, canvasY1), INK);
				}
			}
		}
	}

	@Override
	public boolean isPauseScreen() {
		return true;
	}

	@Override
	public boolean shouldCloseOnEsc() {
		return false;
	}

	@Override
	public void onClose() {
		// No escaping homework! The only way out is the Done button.
		if (finished) {
			super.onClose();
		}
	}
}
