// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Gate evidence for the START RUN status banner on the Speedrun Home page.
// When the Qt shell cannot launch a real study session (exam deck missing, or
// nothing due) it drives an in-page banner via window.speedrunStartStatus so
// the user is never dumped at the bare Anki "Congratulations" dead-end. This
// test proves the banner UI renders both states with the right text + button:
//   (a) "importNeeded" -> "Import the GRE exam deck..." + an "Import deck" btn,
//   (b) "caughtUp" with n -> "All caught up..." + the unlock hint + a
//       "Custom Study" btn,
// and captures a screenshot of each for human review.
//
// SCOPE NOTE: this exercises only the SvelteKit banner UI (invoked directly via
// window.speedrunStartStatus, exactly as the Qt shell calls it through
// web.eval). The Qt-side branching (no-deck / due / nothing-due -> which state
// fires) is David's `just run` visual gate; it cannot be driven headlessly.

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";
const IMPORT_SHOT = `${SCRATCH}/s1-banner-import.png`;
const CAUGHTUP_SHOT = `${SCRATCH}/s1-banner-caughtup.png`;

test("startrun banner renders importNeeded + caughtUp states", async ({ page }) => {
    // Navigate and let the page settle so window.speedrunStartStatus is wired
    // (registered onMount by SpeedrunHome.svelte).
    await page.goto("/speedrun-home", { waitUntil: "networkidle" });

    // Sanity: the hook the Qt shell calls must exist on the page.
    const hasHook = await page.evaluate(
        () =>
            typeof (window as unknown as { speedrunStartStatus?: unknown }).speedrunStartStatus
                === "function",
    );
    expect(hasHook, "window.speedrunStartStatus must be registered onMount").toBe(true);

    // (a) importNeeded state.
    await page.evaluate(() =>
        (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
            .speedrunStartStatus("importNeeded")
    );
    const banner = page.locator(".startstatus");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Import the GRE exam deck to start a run.");
    await expect(page.getByRole("button", { name: "Import deck" })).toBeVisible();
    await page.screenshot({ path: IMPORT_SHOT, fullPage: true });

    // (b) caughtUp state with an unlock count.
    await page.evaluate(() =>
        (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
            .speedrunStartStatus("caughtUp", 5)
    );
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("All caught up for today.");
    await expect(banner).toContainText("5 new cards will unlock next.");
    await expect(page.getByRole("button", { name: "Custom Study" })).toBeVisible();
    await page.screenshot({ path: CAUGHTUP_SHOT, fullPage: true });
});
