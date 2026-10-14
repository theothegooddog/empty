package com.homeworkbreak;

import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.MultiLineTextWidget;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

public class HomeworkScreen extends Screen {
	private static final int WHITE = 0xFFFFFFFF;
	private static final int YELLOW = 0xFFFFFF55;
	private static final int GRAY = 0xFFAAAAAA;
	private static final int PANEL = 0xC0000000;

	private final String question;
	private final int number;
	private final int total;
	private final long unlockAtMillis;

	private MultiLineTextWidget questionText;
	private Button doneButton;
	private boolean finished;

	public HomeworkScreen(String question, int number, int total, int minSeconds) {
		super(Component.literal("Homework Break!"));
		this.question = question;
		this.number = number;
		this.total = total;
		this.unlockAtMillis = System.currentTimeMillis() + minSeconds * 1000L;
	}

	@Override
	protected void init() {
		int panelWidth = Math.min(340, this.width - 40);

		questionText = new MultiLineTextWidget(Component.literal(question), this.font)
				.setMaxWidth(panelWidth - 20)
				.setCentered(true);
		questionText.setX(this.width / 2 - (panelWidth - 20) / 2);
		questionText.setY(this.height / 2 - 40);
		addRenderableOnly(questionText);

		doneButton = addRenderableWidget(Button.builder(Component.empty(), b -> finish())
				.bounds(this.width / 2 - 110, this.height / 2 + 50, 220, 20)
				.build());
		updateButton();
	}

	private int secondsLeft() {
		long ms = unlockAtMillis - System.currentTimeMillis();
		return ms <= 0 ? 0 : (int) ((ms + 999) / 1000);
	}

	private void updateButton() {
		int left = secondsLeft();
		doneButton.active = left == 0;
		doneButton.setMessage(left == 0
				? Component.literal("I wrote it on my paper ✔")
				: Component.literal("Keep working... (" + left + "s)"));
	}

	@Override
	public void tick() {
		updateButton();
	}

	private void finish() {
		if (secondsLeft() > 0) {
			return;
		}
		finished = true;
		HomeworkBreakClient.questionFinished();
		this.minecraft.gui.setScreen(null);
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor g, int mouseX, int mouseY, float partialTick) {
		updateButton();

		int panelWidth = Math.min(340, this.width - 40);
		int left = this.width / 2 - panelWidth / 2;
		int top = this.height / 2 - 85;
		int bottom = this.height / 2 + 82;
		g.fill(left, top, left + panelWidth, bottom, PANEL);

		g.centeredText(this.font, this.title, this.width / 2, top + 10, YELLOW);
		g.centeredText(this.font, "Question " + number + " of " + total, this.width / 2, top + 24, GRAY);

		super.extractRenderState(g, mouseX, mouseY, partialTick);

		int belowQuestion = Math.max(questionText.getY() + questionText.getHeight() + 10, this.height / 2 + 20);
		g.centeredText(this.font, "Work it out and write your answer on your homework paper.",
				this.width / 2, Math.min(belowQuestion, this.height / 2 + 36), WHITE);
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
		// No escaping homework! The only way out is the "I wrote it on my paper" button.
		if (finished) {
			super.onClose();
		}
	}
}
