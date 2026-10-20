import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Feature 006, end to end: a file attached to a new chat becomes a chip, and
 * hovering or focusing that chip previews the file (name, type and size).
 */
test("a file chip previews its file on hover and on keyboard focus", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.goto("/workspace/chats/new");
  const attach = page.getByRole("button", { name: "Attach file" });
  await expect(attach).toBeVisible({ timeout: 15_000 });
  const chooser = page.waitForEvent("filechooser");
  await attach.click();
  await (
    await chooser
  ).setFiles({
    name: "report.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("a,b\n1,2\n"),
  });
  const chip = page.getByTestId("chip-file").filter({ hasText: "report.csv" });
  await expect(chip).toBeVisible();

  await chip.hover();
  const preview = page.getByTestId("file-preview");
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("report.csv");
  await expect(preview).toContainText("text/csv · 8 bytes");

  await page.mouse.move(5, 5);
  await expect(preview).toHaveCount(0);
  await page.getByRole("button", { name: "Remove file report.csv" }).focus();
  await expect(preview).toBeVisible();
});
