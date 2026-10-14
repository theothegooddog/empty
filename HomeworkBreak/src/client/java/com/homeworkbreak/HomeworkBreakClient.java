package com.homeworkbreak;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.ThreadLocalRandom;

public class HomeworkBreakClient implements ClientModInitializer {
	public static final Logger LOGGER = LoggerFactory.getLogger("homeworkbreak");

	private static int ticksUntilBreak;
	/** True while a question has been shown but not finished yet, so it comes back if something closes it. */
	private static boolean questionPending;

	@Override
	public void onInitializeClient() {
		HomeworkConfig.load();
		scheduleNextBreak();
		ClientTickEvents.END_CLIENT_TICK.register(HomeworkBreakClient::onTick);
	}

	private static void onTick(Minecraft mc) {
		// Only count time you're actually playing: in a world, with no menu open.
		if (mc.player == null || mc.gui.screen() != null) {
			return;
		}
		if (questionPending || --ticksUntilBreak <= 0) {
			showQuestion(mc);
		}
	}

	private static void showQuestion(Minecraft mc) {
		HomeworkConfig.reloadQuestions();
		if (!HomeworkConfig.hasNextQuestion()) {
			questionPending = false;
			scheduleNextBreak();
			return;
		}
		questionPending = true;
		mc.gui.setScreen(new HomeworkScreen(
				HomeworkConfig.nextQuestion(),
				HomeworkConfig.nextIndex() + 1,
				HomeworkConfig.questionCount(),
				HomeworkConfig.minSecondsPerQuestion));
	}

	static void questionFinished() {
		HomeworkConfig.markCurrentDone();
		questionPending = false;
		scheduleNextBreak();
	}

	private static void scheduleNextBreak() {
		int minutes = ThreadLocalRandom.current().nextInt(HomeworkConfig.minMinutes, HomeworkConfig.maxMinutes + 1);
		ticksUntilBreak = minutes * 60 * 20;
	}
}
