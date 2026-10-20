import { expect, test, type Page } from "@playwright/test";

import { THREAD, bar, message, stub } from "./chat-bar-stubs";
import { lowContrastText } from "./contrast-probe";

/**
 * File chips preview their file (Feature 006): hovering or focusing a file
 * chip shows a thumbnail for an image, and the name, type and size for any
 * other file. Keyboard: the chip (reached from the message with Backspace)
 * and its × both open it, and it describes them while open.
 */

// A 1 x 1 PNG.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function attach(
  page: Page,
  files: { name: string; mimeType: string; buffer: Buffer }[],
) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Attach file" }).click();
  await (await chooser).setFiles(files);
  await expect(bar(page).getByTestId("chip-file")).toHaveCount(files.length);
}

const chipFor = (page: Page, name: string) =>
  bar(page).getByTestId("chip-file").filter({ hasText: name });

test("hovering a file chip shows its name, type and size; an image shows a thumbnail", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await attach(page, [
    {
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("x".repeat(1536)),
    },
    { name: "shot.png", mimeType: "image/png", buffer: PNG },
  ]);

  await chipFor(page, "notes.txt").hover();
  const preview = page.getByTestId("file-preview");
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("notes.txt");
  await expect(preview).toContainText("text/plain · 1.5 KB");
  await expect(preview.getByRole("img")).toHaveCount(0);

  await page.mouse.move(5, 5);
  await expect(preview).toHaveCount(0);

  await chipFor(page, "shot.png").hover();
  await expect(preview).toBeVisible();
  const thumb = preview.getByRole("img", { name: "Preview of shot.png" });
  await expect(thumb).toBeVisible();
  expect(
    await thumb.evaluate((el) => (el as HTMLImageElement).naturalWidth),
  ).toBe(1);
  await expect(preview).toContainText("image/png · 70 bytes");

  // Only file chips preview: the agent chip does not.
  await page.mouse.move(5, 5);
  await bar(page).getByTestId("chip-agent").hover();
  await page.waitForTimeout(400);
  await expect(preview).toHaveCount(0);
});

test("keyboard: focusing a file chip or its × opens the preview and it describes them", async ({
  page,
}) => {
  await stub(page);
  await page.goto(`/workspace/chats/${THREAD}`);
  await attach(page, [
    { name: "plan.zzq", mimeType: "", buffer: Buffer.from("# plan") },
  ]);
  await message(page).focus();
  await page.keyboard.press("Backspace");
  const chip = chipFor(page, "plan.zzq");
  await expect(chip).toBeFocused();
  const preview = page.getByTestId("file-preview");
  await expect(preview).toBeVisible();
  // No media type from the browser: the extension, said as such.
  await expect(preview).toContainText("ZZQ file · 6 bytes");
  const id = await preview.getAttribute("id");
  await expect(chip).toHaveAttribute("aria-describedby", id!);

  // Esc goes back to the message, and the preview closes.
  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);

  const remove = page.getByRole("button", { name: "Remove file plan.zzq" });
  await remove.focus();
  await expect(preview).toBeVisible();
  await expect(remove).toHaveAttribute("aria-describedby", id!);
});

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: the file preview meets WCAG AA`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => {
      try {
        localStorage.setItem("theme", t);
      } catch {}
    }, scheme);
    await stub(page);
    await page.goto(`/workspace/chats/${THREAD}`, { waitUntil: "networkidle" });
    await attach(page, [
      { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hi") },
    ]);
    await chipFor(page, "notes.txt").hover();
    await expect(page.getByTestId("file-preview")).toBeVisible();
    await page.waitForTimeout(300);
    const found = await page.evaluate(lowContrastText);
    expect(
      found,
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
    ).toEqual([]);
  });
}
