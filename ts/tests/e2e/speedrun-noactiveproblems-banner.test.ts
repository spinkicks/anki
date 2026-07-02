// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// TEMPORARY gate evidence (UNSTAGED) for the START RUN "noActiveProblems"
// status banner. When the GRE Problems subdeck IS imported but every problem
// card is SUSPENDED, the Qt shell drives an in-page informational banner via
// window.speedrunStartStatus("noActiveProblems") (distinct from importNeeded).
// This test proves the banner renders the HONEST unsuspend copy verbatim, is
// INFORMATIONAL (no action button — dismiss ✕ only), reuses the shared
// .startstatus styling, and is clean/console-error-free with no horizontal
// overflow at 360px — at BOTH mobile (360px) and desktop widths.
//
// Mirrors speedrun-mockfailed-banner.test.ts.

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const HONEST_COPY =
    "Your GRE problem bank is all suspended — unsuspend problems (Browse ▸ select ▸ Toggle Suspend) to run a timed mini-mock.";

const WIDTHS = [
    { label: "mobile", width: 360, height: 800, shot: `${SCRATCH}/p2-noactiveproblems-360.png` },
    { label: "desktop", width: 1280, height: 900, shot: `${SCRATCH}/p2-noactiveproblems-desktop.png` },
] as const;

for (const vp of WIDTHS) {
    test(`startrun banner renders noActiveProblems honest state at ${vp.label} (${vp.width}px)`, async ({ page }) => {
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

        // Fire the noActiveProblems state exactly as the Qt shell does via
        // web.eval (no n argument, mirroring qt/aqt/speedrun.py).
        await page.evaluate(() =>
            (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
                .speedrunStartStatus("noActiveProblems")
        );

        const banner = page.locator(".startstatus");
        await expect(banner).toBeVisible();

        // (a) The honest unsuspend copy renders verbatim.
        await expect(banner).toContainText(HONEST_COPY);
        const observedText = await banner.locator(".startstatus-text").innerText();

        // (b) INFORMATIONAL: no action button in this branch. Only the dismiss ✕
        //     button (aria-label "Dismiss") may be present.
        const actionBtns = await banner.locator(".startstatus-btn").count();
        expect(actionBtns, "noActiveProblems must have NO action button").toBe(0);
        // The dismiss ✕ is fine (and should be the only button in the banner).
        const dismiss = page.getByRole("button", { name: "Dismiss" });
        await expect(dismiss).toBeVisible();
        const totalBtns = await banner.locator("button").count();
        expect(totalBtns, "only the dismiss ✕ button should exist").toBe(1);

        // (c) Same .startstatus styling as the other banner states: spot-check the
        //     computed styles that define the shared banner look. Compare against
        //     caughtUp (a known-good sibling state).
        const napStyles = await banner.evaluate((el) => {
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
        expect(napStyles).toEqual(caughtUpStyles);
        // And it is genuinely the flat/sharp banner (dark panel, accent left rule).
        expect(napStyles.display).toBe("flex");
        expect(parseInt(napStyles.borderLeft)).toBeGreaterThanOrEqual(3);

        // Also spot-check the text style token matches a sibling informational
        // state's text (font-size/color/transform on .startstatus-text).
        const napTextStyle = await banner.locator(".startstatus-text").evaluate((el) => {
            const s = getComputedStyle(el);
            return {
                fontSize: s.fontSize,
                color: s.color,
                textTransform: s.textTransform,
            };
        });

        // Re-fire noActiveProblems for the screenshot state.
        await page.evaluate(() =>
            (window as unknown as { speedrunStartStatus: (s: string, n?: number) => void })
                .speedrunStartStatus("noActiveProblems")
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

        // Emit observed evidence to the test log.
        console.log(
            `[noActiveProblems ${vp.label}] text=${JSON.stringify(observedText)} `
                + `styles=${JSON.stringify(napStyles)} textStyle=${JSON.stringify(napTextStyle)} `
                + `actionBtns=${actionBtns} totalBtns=${totalBtns}`,
        );

        // (f) Zero console errors, zero failed /_anki/* requests.
        expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
        expect(failedAnki, `failed /_anki/* requests: ${failedAnki.join(" | ")}`).toEqual([]);
    });
}
