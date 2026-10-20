import { expect, test, type Page, type Request } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";

/**
 * Revealing a stored MCP secret asks for the account password first.
 *
 * NO BACKEND: /api is intercepted, so this asserts the UI given the gateway's
 * answers. The gateway side (owner only, password check, lockout, audit log
 * by key name) is pytest's: backend/tests/mcp_studio/test_secret_reveal.py.
 */

const PASSWORD = "Str0ng!Pass99";
const VALUE = "ghp_SuperSecretValue_8f2k1";
const now = () => new Date().toISOString();

const SERVER = {
  id: "weather",
  name: "weather-server",
  language: "python",
  description: "Wraps an internal API.",
  status: "verified",
  phase: "verified",
  approved: false,
  detected_secrets: ["GITHUB_TOKEN"],
  egress_hosts: [],
  source_code: "print('x')\n",
  files: { "server.py": "print('x')\n" },
  created_at: now(),
  updated_at: now(),
};
const BUILD = {
  server_id: "weather",
  phase: "verified",
  tools_discovered: [{ name: "list_issues", description: "List issues." }],
  detected_secret_names: ["GITHUB_TOKEN"],
  errors: [],
  test_results: [],
  last_verified_at: now(),
  deploy_steps: [],
};

async function stub(page: Page, reveals: Request[]) {
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  await page.route("**/api/**", (route) => route.fulfill(json({})));
  await page.route("**/api/mcp-studio/servers/weather", (route) =>
    route.fulfill(json(SERVER)),
  );
  await page.route("**/api/mcp-studio/servers/weather/build", (route) =>
    route.fulfill(json(BUILD)),
  );
  await page.route("**/api/mcp-studio/servers/weather/secrets/info", (route) =>
    route.fulfill(
      json({ keys: [{ key_name: "GITHUB_TOKEN", key_hint: "8f2k1" }] }),
    ),
  );
  await page.route(
    "**/api/mcp-studio/servers/weather/secrets/reveal**",
    (route) => {
      const req = route.request();
      reveals.push(req);
      const body = JSON.parse(req.postData() ?? "{}") as { password?: string };
      return route.fulfill(
        body.password === PASSWORD
          ? json({ values: { GITHUB_TOKEN: VALUE } })
          : json({ detail: "Password is incorrect." }, 403),
      );
    },
  );
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });

    test("reveal asks for the password in a labelled, trapped dialog", async ({
      page,
    }) => {
      await page.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, scheme);
      const reveals: Request[] = [];
      await stub(page, reveals);
      await page.goto("/workspace/mcp/weather", { waitUntil: "networkidle" });
      expect(
        await page.evaluate(() =>
          document.documentElement.classList.contains("dark"),
        ),
      ).toBe(scheme === "dark");

      const eye = page.getByRole("button", {
        name: "Reveal stored value: GITHUB_TOKEN",
      });
      await eye.click();

      // Labelled by its title, focus inside on the password field.
      const dialog = page.getByRole("dialog", { name: "Reveal GITHUB_TOKEN" });
      await expect(dialog).toBeVisible();
      const field = dialog.getByLabel("Your password");
      await expect(field).toBeFocused();
      expect(reveals, "nothing is revealed before the password").toHaveLength(
        0,
      );

      // Text in the dialog meets AA in this theme.
      const low = (await page.evaluate(lowContrastText)).filter((f) =>
        /Reveal|password|recorded|Cancel/i.test(f.text),
      );
      expect(low, JSON.stringify(low)).toEqual([]);

      // Tab stays inside the dialog.
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press("Tab");
        expect(
          await dialog.evaluate((d) => d.contains(document.activeElement)),
        ).toBe(true);
      }

      // Esc closes it and gives focus back to the eye button.
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(eye).toBeFocused();

      // A wrong password is refused in words; the value never shows.
      await eye.click();
      await dialog.getByLabel("Your password").fill("wrong-password");
      await dialog.getByRole("button", { name: "Reveal" }).click();
      await expect(dialog.getByRole("alert")).toHaveText(
        "That password is not right.",
      );
      await expect(page.locator(`input[value="${VALUE}"]`)).toHaveCount(0);

      // The right password reveals it, sent in the body and not the URL.
      await dialog.getByLabel("Your password").fill(PASSWORD);
      await dialog.getByRole("button", { name: "Reveal" }).click();
      await expect(dialog).toBeHidden();
      await expect(page.locator(`input[value="${VALUE}"]`)).toHaveCount(1);
      const last = reveals.at(-1)!;
      expect(last.method()).toBe("POST");
      expect(last.url()).not.toContain(PASSWORD);
      expect(JSON.parse(last.postData()!)).toEqual({
        key_name: "GITHUB_TOKEN",
        password: PASSWORD,
      });
    });
  });
}

test("a delete the gateway refuses is said in words, and the server stays", async ({
  page,
}) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  // The Build board (#59) lists servers at /servers and discards one with
  // "Discard" then "Discard <name>".
  for (const glob of [
    "**/api/mcp-studio/servers?**",
    "**/api/mcp-studio/servers",
  ]) {
    await page.route(glob, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          servers: [
            {
              ...SERVER,
              state: "awaiting_approval",
              state_label: "Waiting for your approval",
              steps: [],
            },
          ],
          total: 1,
        }),
      }),
    );
  }
  await page.route("**/api/mcp-studio/servers/weather", (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill({
          status: 502,
          contentType: "application/json",
          body: JSON.stringify({
            detail:
              "The server was not deleted: docker rm omni-mcp-weather failed: permission denied",
          }),
        })
      : route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SERVER),
        }),
  );
  await page.goto("/workspace/connections?tab=build", {
    waitUntil: "networkidle",
  });
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  await page.getByRole("button", { name: "Discard weather-server" }).click();
  // (Next's route announcer is also role=alert.)
  await expect(
    page.getByRole("alert").filter({ hasText: "Not deleted" }),
  ).toContainText(
    "Not deleted: The server was not deleted: docker rm omni-mcp-weather failed: permission denied",
  );
  await expect(page.getByTestId("built-detail")).toContainText(
    "weather-server",
  );
});
