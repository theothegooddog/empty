package com.homeworkbreak;

import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.resources.Identifier;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * A photo of a homework question, shown in the game. The photo is shrunk to exactly the
 * number of screen pixels it's drawn at (averaging pixels, not skipping them), so the
 * handwriting or print stays readable instead of turning into jagged pixels.
 */
public final class QuestionPicture implements AutoCloseable {
	private static final AtomicInteger NEXT_ID = new AtomicInteger();

	private final NativeImage source;
	private final Identifier textureId;
	private int textureWidth = -1;
	private int textureHeight = -1;

	private QuestionPicture(NativeImage source) {
		this.source = source;
		this.textureId = Identifier.fromNamespaceAndPath("homeworkbreak", "question_picture_" + NEXT_ID.getAndIncrement());
	}

	/** Loads a PNG from the scans folder, or returns null if it can't be read. */
	public static QuestionPicture load(Path file) {
		try (InputStream in = Files.newInputStream(file)) {
			return new QuestionPicture(NativeImage.read(in));
		} catch (IOException e) {
			HomeworkBreakClient.LOGGER.error("Could not load question picture {}", file, e);
			return null;
		}
	}

	public int width() {
		return source.getWidth();
	}

	public int height() {
		return source.getHeight();
	}

	/** Draws the picture into the given GUI rectangle. */
	public void draw(GuiGraphicsExtractor g, int x, int y, int w, int h) {
		if (w <= 0 || h <= 0) {
			return;
		}
		int scale = Minecraft.getInstance().getWindow().getGuiScale();
		ensureTexture(w * scale, h * scale);
		g.blit(RenderPipelines.GUI_TEXTURED, textureId, x, y, 0, 0, w, h, textureWidth, textureHeight, textureWidth, textureHeight);
	}

	private void ensureTexture(int pixelWidth, int pixelHeight) {
		if (pixelWidth == textureWidth && pixelHeight == textureHeight) {
			return;
		}
		NativeImage scaled = resize(source, pixelWidth, pixelHeight);
		Minecraft.getInstance().getTextureManager().release(textureId);
		Minecraft.getInstance().getTextureManager().register(textureId, new DynamicTexture(() -> "Homework question picture", scaled));
		textureWidth = pixelWidth;
		textureHeight = pixelHeight;
	}

	/** Box-filter resize: each new pixel is the average of the source pixels it covers. */
	private static NativeImage resize(NativeImage src, int newW, int newH) {
		int srcW = src.getWidth();
		int srcH = src.getHeight();
		NativeImage out = new NativeImage(newW, newH, false);
		double sx = (double) srcW / newW;
		double sy = (double) srcH / newH;
		for (int ty = 0; ty < newH; ty++) {
			int y0 = (int) (ty * sy);
			int y1 = Math.max(y0 + 1, Math.min(srcH, (int) Math.ceil((ty + 1) * sy)));
			for (int tx = 0; tx < newW; tx++) {
				int x0 = (int) (tx * sx);
				int x1 = Math.max(x0 + 1, Math.min(srcW, (int) Math.ceil((tx + 1) * sx)));
				long a = 0, r = 0, gr = 0, b = 0;
				int n = 0;
				for (int y = y0; y < y1; y++) {
					for (int x = x0; x < x1; x++) {
						int argb = src.getPixel(x, y);
						a += argb >>> 24;
						r += (argb >> 16) & 0xFF;
						gr += (argb >> 8) & 0xFF;
						b += argb & 0xFF;
						n++;
					}
				}
				out.setPixel(tx, ty, (int) (a / n) << 24 | (int) (r / n) << 16 | (int) (gr / n) << 8 | (int) (b / n));
			}
		}
		return out;
	}

	@Override
	public void close() {
		Minecraft.getInstance().getTextureManager().release(textureId);
		source.close();
	}
}
