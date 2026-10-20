import { expect, test } from "@playwright/test";

/**
 * Settings > Account: the optional display name (Feature 006). The gateway is
 * stubbed; the server half (storage, the fallback rule) is tested through
 * create_app() in backend/tests/preferences.
 */
const ok = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const prefs = (display_name: string | null) => ({
  appearance: "system",
  appearance_chosen: false,
  display_name,
  display_name_effective: display_name ?? "e2e",
});

test("an unset name shows the fallback, and a set one is saved", async ({
  page,
}) => {
  const puts: unknown[] = [];
  await page.route("**/api/preferences/display-name", async (route) => {
    const body = route.request().postDataJSON() as {
      display_name: string | null;
    };
    puts.push(body);
    await route.fulfill(ok(prefs(body.display_name)));
  });
  await page.route("**/api/preferences", (route) =>
    route.fulfill(ok(prefs(null))),
  );
  await page.goto("/workspace/settings/account");
  const field = page.getByLabel("Display name");
  await expect(field).toBeEnabled();
  await expect(field).toHaveValue("");
  await expect(field).toHaveAttribute("placeholder", "e2e");
  await expect(page.getByTestId("display-name-status")).toContainText(
    "instead of e2e",
  );
  await field.fill("  Rishabh ");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByTestId("display-name-status")).toHaveText("Saved.");
  expect(puts).toEqual([{ display_name: "Rishabh" }]);
});

test("a name that cannot be loaded is said, and cannot be edited", async ({
  page,
}) => {
  await page.route("**/api/preferences", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/workspace/settings/account");
  await expect(page.getByTestId("display-name-status")).toHaveText(
    "Could not load your name.",
    { timeout: 15_000 },
  );
  await expect(page.getByLabel("Display name")).toBeDisabled();
});
