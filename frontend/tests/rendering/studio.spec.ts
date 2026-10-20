import { expect, test, type Page } from "@playwright/test";

import { lowContrastText } from "./contrast-probe";
import { stubStudio } from "./studio-stubs";

/**
 * Agent Studio and Skill Studio (Feature 006, Phase 3), as the capsule's
 * Agents and Skills panels: the board's layout (Agent-Studio.dc.html,
 * Skill-Studio.dc.html), real tablists, one solid button, AA contrast in both
 * themes on every tab, and the honest states (deleted, switched off).
 *
 * Set STUDIO_SHOTS to a directory to save each screen in both themes.
 */

async function inTheme(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, scheme);
}

async function noLowContrast(page: Page, where: string) {
  const found = await page.evaluate(lowContrastText);
  expect(
    found,
    `${where}\n` +
      found
        .map((f) => `${f.ratio}/${f.need} "${f.text}" ${f.color} [${f.cls}]`)
        .join("\n"),
  ).toEqual([]);
}

async function shot(page: Page, name: string) {
  const dir = process.env.STUDIO_SHOTS;
  if (dir) await page.screenshot({ path: `${dir}/${name}.png` });
}

const sheet = (page: Page) => page.getByTestId("panel-sheet");

for (const scheme of ["dark", "light"] as const) {
  test(`${scheme}: Agent Studio matches the board and every tab meets AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stubStudio(page);
    await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
      waitUntil: "networkidle",
    });
    const studio = page.getByTestId("agent-studio");
    await expect(studio).toBeVisible();
    await expect(page.getByTestId("studio-title")).toHaveValue(
      "Evening wrap-up",
    );

    // Rail: 250 wide, "+ New agent" dashed, the lead agent then the custom
    // agents with 26 px avatars, the selected one marked.
    const rail = page.getByTestId("studio-rail");
    expect((await rail.boundingBox())!.width).toBeCloseTo(250, 0);
    await expect(page.getByTestId("studio-new")).toHaveText("+ New agent");
    expect(
      await page
        .getByTestId("studio-new")
        .evaluate((el) => getComputedStyle(el).borderStyle),
    ).toBe("dashed");
    await expect(rail.getByRole("button")).toHaveText([
      "+ New agent",
      "LLead agent",
      "ReResearcher",
      "EWEvening wrap-up",
      "RMRelease manager",
    ]);
    await expect(
      page.getByTestId("studio-item-evening-wrap-up"),
    ).toHaveAttribute("aria-current", "page");

    // A real tablist with the board's five tabs, Overview selected.
    const tabs = page.getByRole("tablist", { name: "Agent settings" });
    await expect(tabs.getByRole("tab")).toHaveText([
      "Overview",
      "Instructions",
      "Tools and skills",
      "Autonomy",
      "Schedule",
    ]);
    await expect(page.getByTestId("studio-tab-overview")).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // Overview: four stat cards, real data.
    await expect(page.getByTestId("overview-works-on")).toContainText(
      "OmniHarness",
    );
    await expect(page.getByTestId("overview-uses")).toContainText(
      "web, file:read · 2 skills",
    );
    // Schedule and runs come from the trigger engine (stubbed here).
    await expect(page.getByTestId("overview-next-run")).toContainText(
      /(Tomorrow|Today|\w{3}) .*\d:\d\d/,
    );
    await expect(page.getByTestId("studio-active")).toHaveText("Active");
    await expect(page.getByTestId("recent-run")).toHaveCount(2);
    await expect(page.getByTestId("recent-run").nth(1)).toContainText(
      "Held · evening-wrap · quiet hours 22:00-07:30",
    );
    await expect(page.getByTestId("overview-on-its-own")).toContainText(
      "Create and update tasks, Add notes and decisions",
    );
    await expect(page.getByTestId("grant-use")).toContainText(
      "suggested by content from web_fetch",
    );
    const radius = await page
      .getByTestId("overview-uses")
      .evaluate((el) => getComputedStyle(el).borderRadius);
    expect(radius).toBe("14px");

    // One solid button on the screen: Save. Test run is an outline.
    const save = page.getByTestId("studio-save");
    await expect(save).toHaveText("Save");
    const solid = await sheet(page).evaluate((root) =>
      Array.from(root.querySelectorAll("button, a"))
        .filter((el) => {
          const bg = getComputedStyle(el).backgroundColor;
          const primary = getComputedStyle(document.documentElement)
            .getPropertyValue("--primary")
            .trim();
          const probe = document.createElement("span");
          probe.style.color = primary;
          document.body.append(probe);
          const p = getComputedStyle(probe).color;
          probe.remove();
          return bg === p;
        })
        .map((el) => el.textContent),
    );
    expect(solid).toEqual(["Save"]);

    await noLowContrast(page, "overview");
    await shot(page, `agent-studio-overview-live-${scheme}`);

    for (const tab of ["instructions", "tools", "autonomy", "schedule"]) {
      await page.getByTestId(`studio-tab-${tab}`).click();
      await expect(page.getByTestId(`studio-tab-${tab}`)).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await page.waitForTimeout(150);
      await noLowContrast(page, tab);
      await shot(page, `agent-studio-${tab}-live-${scheme}`);
    }
  });

  test(`${scheme}: Skill Studio matches the board and every tab meets AA`, async ({
    page,
  }) => {
    await inTheme(page, scheme);
    await stubStudio(page);
    await page.goto(
      "/workspace/chats?panel=skills&item=project-status-format",
      {
        waitUntil: "networkidle",
      },
    );
    await expect(page.getByTestId("skill-studio")).toBeVisible();
    await expect(page.getByTestId("studio-title")).toHaveText(
      "Project status format",
    );
    await expect(sheet(page)).toContainText(
      "Used by Lead agent, Researcher, Evening wrap-up and Release manager",
    );
    await expect(
      page.getByRole("tablist", { name: "Skill settings" }).getByRole("tab"),
    ).toHaveText(["Details", "Instructions", "Files", "Test"]);
    const name = page.getByTestId("skill-name");
    expect((await name.boundingBox())!.width).toBeLessThanOrEqual(480);
    await expect(page.getByTestId("skill-when")).toHaveValue(
      /where are we on X/,
    );
    await expect(sheet(page)).toContainText(
      "This sentence decides when the skill loads.",
    );
    await expect(page.getByTestId("studio-save")).toHaveText("Save skill");
    await noLowContrast(page, "details");
    await shot(page, `skill-studio-details-live-${scheme}`);

    await page.getByTestId("studio-tab-instructions").click();
    await expect(
      page.getByRole("toolbar", { name: "Formatting" }),
    ).toBeVisible();
    await page.getByTestId("skill-preview-toggle").click();
    await expect(page.getByTestId("skill-body-preview")).toContainText(
      "Status report format",
    );
    expect(
      (await page.getByTestId("skill-body-preview").boundingBox())!.height,
    ).toBeGreaterThanOrEqual(220);
    await noLowContrast(page, "instructions");
    await shot(page, `skill-studio-instructions-live-${scheme}`);

    await page.getByTestId("studio-tab-files").click();
    await expect(page.getByTestId("skill-file")).toHaveCount(2);
    await expect(page.getByTestId("skill-file").first()).toContainText("2 KB");
    await noLowContrast(page, "files");
    await shot(page, `skill-studio-files-live-${scheme}`);

    await page.getByTestId("studio-tab-test").click();
    await noLowContrast(page, "test");
    await shot(page, `skill-studio-test-live-${scheme}`);
  });
}

test("the tabs move with the arrow keys", async ({ page }) => {
  await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await page.getByTestId("studio-tab-overview").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("studio-tab-instructions")).toBeFocused();
  await expect(page.getByTestId("studio-tab-instructions")).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("End");
  await expect(page.getByTestId("studio-tab-schedule")).toBeFocused();
});

test("an agent no automation runs says Not set up, and why", async ({
  page,
}) => {
  await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=researcher", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("overview-next-run")).toContainText(
    "Not set up",
  );
  await expect(page.getByTestId("studio-active")).toHaveCount(0);
  await expect(page.getByTestId("recent-runs")).toContainText(
    "No automation runs this agent yet",
  );
  await page.getByTestId("studio-tab-schedule").click();
  await expect(page.getByTestId("schedule-none")).toContainText(
    "every automation runs as the lead agent",
  );
});

test("a link to an agent that no longer exists says so", async ({ page }) => {
  await stubStudio(page);
  await page.goto("/workspace/chats?panel=agents&item=deleted-one", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("studio-gone")).toHaveText(
    '"deleted-one" no longer exists. It may have been deleted.',
  );
});

test("switched-off custom agents say so, and the lead agent still shows", async ({
  page,
}) => {
  await stubStudio(page, { agentsDisabled: true });
  await page.goto("/workspace/chats?panel=agents", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("studio-item-lead")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByTestId("studio-new").click();
  await expect(page.getByTestId("agents-disabled")).toContainText(
    "Custom agents are turned off",
  );
});

test("at phone width the rail stacks and every target is 44 px tall", async ({
  page,
}) => {
  await stubStudio(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workspace/chats?panel=agents&item=evening-wrap-up", {
    waitUntil: "networkidle",
  });
  await expect(page.getByTestId("agent-studio")).toBeVisible();
  const small = await page.getByTestId("agent-studio").evaluate((root) =>
    Array.from(root.querySelectorAll<HTMLElement>("button, [role=tab], a"))
      .filter((el) => el.offsetParent !== null)
      .filter((el) => el.getBoundingClientRect().height < 44)
      .map((el) => el.textContent),
  );
  expect(small).toEqual([]);
});
