package com.homeworkbreak;

import com.mojang.brigadier.Command;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.command.v2.ClientCommands;
import net.fabricmc.fabric.api.client.command.v2.FabricClientCommandSource;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.minecraft.ChatFormatting;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.util.Util;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.util.concurrent.ThreadLocalRandom;

public class HomeworkBreakClient implements ClientModInitializer {
	public static final Logger LOGGER = LoggerFactory.getLogger("homeworkbreak");

	private static int ticksUntilBreak;
	/** Set when a break is due; the question shows as soon as no other menu is open. */
	private static boolean breakDue;
	/** The question currently on screen (or interrupted by another screen), so it comes back. */
	private static String pendingQuestionId;

	@Override
	public void onInitializeClient() {
		HomeworkConfig.load();
		HomeworkStore.load();
		HomeworkServer.start();
		scheduleNextBreak();

		ClientTickEvents.END_CLIENT_TICK.register(HomeworkBreakClient::onTick);

		ClientCommandRegistrationCallback.EVENT.register((dispatcher, context) -> dispatcher.register(
				ClientCommands.literal("homework")
						.executes(c -> openPage(c.getSource(), ""))
						.then(ClientCommands.literal("scan").executes(c -> openPage(c.getSource(), "")))
						.then(ClientCommands.literal("print").executes(c -> openPage(c.getSource(), "print")))
						.then(ClientCommands.literal("now").executes(c -> {
							breakDue = true;
							return Command.SINGLE_SUCCESS;
						}))));

		ScreenEvents.AFTER_INIT.register((mc, screen, width, height) -> {
			if (screen instanceof PauseScreen) {
				Screens.getWidgets(screen).add(Button.builder(Component.literal("Homework"), b -> openInBrowser(""))
						.bounds(6, 6, 70, 20)
						.build());
			}
		});
	}

	private static void onTick(Minecraft mc) {
		// Only count time you're actually playing: in a world, with no menu open.
		if (mc.player == null || mc.gui.screen() != null) {
			return;
		}
		if (pendingQuestionId == null && !breakDue && --ticksUntilBreak <= 0) {
			breakDue = true;
		}
		if (pendingQuestionId != null || breakDue) {
			showQuestion(mc);
		}
	}

	private static void showQuestion(Minecraft mc) {
		breakDue = false;
		HomeworkStore.importQuestionsTxt();
		HomeworkStore.Question q = HomeworkStore.nextQuestion();
		if (q == null) {
			pendingQuestionId = null;
			scheduleNextBreak();
			return;
		}
		pendingQuestionId = q.id;
		int[] pos = HomeworkStore.positionOf(q.id);
		mc.gui.setScreen(new HomeworkScreen(q, pos[0], pos[1], HomeworkConfig.minSecondsPerQuestion));
	}

	static void questionFinished() {
		pendingQuestionId = null;
		scheduleNextBreak();
	}

	private static void scheduleNextBreak() {
		int minutes = ThreadLocalRandom.current().nextInt(HomeworkConfig.minMinutes, HomeworkConfig.maxMinutes + 1);
		ticksUntilBreak = minutes * 60 * 20;
	}

	private static int openPage(FabricClientCommandSource source, String path) {
		if (!HomeworkServer.isRunning()) {
			source.sendError(Component.literal("The homework page couldn't start. Try changing web_page_port in settings.properties."));
			return 0;
		}
		String url = HomeworkServer.url(path);
		openInBrowser(path);
		source.sendFeedback(Component.literal("Opened your homework page in the browser: ")
				.append(Component.literal(url).withStyle(s -> s
						.withColor(ChatFormatting.AQUA)
						.withUnderlined(true)
						.withClickEvent(new ClickEvent.OpenUrl(URI.create(url))))));
		return Command.SINGLE_SUCCESS;
	}

	private static void openInBrowser(String path) {
		Util.getPlatform().openUri(HomeworkServer.url(path));
	}
}
