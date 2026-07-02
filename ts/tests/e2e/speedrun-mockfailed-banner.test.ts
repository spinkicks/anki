// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// P2 gate evidence for the START RUN "mockFailed" status banner. When the Qt
// shell can't build the timed mini-mock (no eligible problems), it drives an
// in-page honest failure banner via window.speedrunStartStatus("mockFailed").
// This test proves the banner renders the HONEST copy + an "Import deck" button,
// reuses the shared .startstatus styling, and is clean/console-error-free with
// no horizontal overflow at 360px — at BOTH mobile (360px) and desktop widths.
//
// Mirrors speedrun-startrun-banner.test.ts (the importNeeded/caughtUp gate).

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const HONEST_COPY =
    "Couldn't start a timed mini-mock — no eligible problems found. Import or unsuspend the GRE problem bank and try again.";

const WIDTHS = [
    { label: "mobile", width: 360, height: 800, shot: `${SCRATCH}/p2-mockfailed-360.png` },
    { label: "desktop", width: 1280, height: 900, shot: `${SCRATCH}/p2-mockfailed-desktop.png` },
] as const;

for (const vp of WIDTHS) {
    test(`startrun banner renders mockFailed honest state at ${vp.label} (${vp.width}px)`, async ({ page }) => {
        // Collect console errors + failed /_anki/* requests across the run.
        const consoleErrors: string[] = [];
        page.on("console", (msg) => {
            if (msg.type() === "error") consoleErrors.push(msg.text());
        });
        const failedAnki: string[] = [];
        page.on("requestfailed", (req) => {
            if (req.url().includes("/_anki/")) failedAnki.push(req.url());
        });
        page.on("response", (resp) => {
            if (resp.url().includes("/_anki/") && resp.status() >= 400) {
                failedAnki.push(`${resp.status()} ${resp.url()}`);
            }
        });

        // Viewport BEFORE navigate so first render lays out for the target width.
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto("/speedrun-home", { waitUntil: "networkidle" });

        // The hook the Qt shell calls must exist (registered onMount).
        const hasHook = await page.evaluate(
            () =>
                typeof (window as unknown as { speedrunStartStatus?: unknown })
                    .speedrunStartStatus === "function",
        );
        expect(hasHook, "window.speedrunStartStatus must be registered onMount").toBe(true);

        // Fire the mockFailed state exactly as the Qt shell does via web.eval.
        await page.evaluate(() =>
            (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
                .speedrunStartStatus("mockFailed")
        );

        const banner = page.locator(".startstatus");
        await expect(banner).toBeVisible();

        // (a) The honest failure copy renders verbatim.
        await expect(banner).toContainText(HONEST_COPY);

        // (b) The "Import deck" button is present.
        const importBtn = page.getByRole("button", { name: "Import deck" });
        await expect(importBtn).toBeVisible();

        // (c) Same .startstatus styling as the other banner states: spot-check the
        //     computed styles that define the shared banner look. Fire caughtUp
        //     (a known-good sibling state) and compare the panel/border tokens.
        const mockStyles = await banner.evaluate((el) => {
            const s = getComputedStyle(el);
            return {
                display: s.display,
                background: s.backgroundColor,
                borderLeft: s.borderLeftWidth + " " + s.borderLeftColor,
                borderBottom: s.borderBottomWidth,
            };
        });
        await page.evaluate(() =>
            (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
                .speedrunStartStatus("caughtUp", 3)
        );
        await expect(banner).toContainText("All caught up");
        const caughtUpStyles = await banner.evaluate((el) => {
            const s = getComputedStyle(el);
            return {
                display: s.display,
                background: s.backgroundColor,
                borderLeft: s.borderLeftWidth + " " + s.borderLeftColor,
                borderBottom: s.borderBottomWidth,
            };
        });
        expect(mockStyles).toEqual(caughtUpStyles);
        // And it is genuinely the flat/sharp banner (dark panel, accent left rule).
        expect(mockStyles.display).toBe("flex");
        expect(parseInt(mockStyles.borderLeft)).toBeGreaterThanOrEqual(3);

        // Re-fire mockFailed for the screenshot state.
        await page.evaluate(() =>
            (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
                .speedrunStartStatus("mockFailed")
        );
        await expect(banner).toContainText(HONEST_COPY);

        // (d) No horizontal overflow at mobile width.
        if (vp.label === "mobile") {
            const overflow = await page.evaluate(
                () => document.documentElement.scrollWidth - window.innerWidth,
            );
            expect(
                overflow,
                `horizontal overflow at ${vp.width}px was ${overflow}px (expected <=2)`,
            ).toBeLessThanOrEqual(2);
        }

        // (e) Screenshot for human review.
        await page.screenshot({ path: vp.shot, fullPage: true });

        // (f) Zero console errors, zero failed /_anki/* requests.
        expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
        expect(failedAnki, `failed /_anki/* requests: ${failedAnki.join(" | ")}`).toEqual([]);
    });
}
