// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// TEMPORARY UI-verification gate for the §7 (LS3) honesty-guardrail copy on the
// shared Speedrun Home dashboard. Leave this file UNSTAGED (the controller does
// not commit it). It drives the real mediasrv-served SvelteKit Home page against
// a live FRESH e2e collection (0 timed problems / 0 calibration attempts =>
// Readiness + Performance abstain) at mobile (360px) and desktop (1280px) and
// asserts:
//   STATIC copy PRESENT (honest in every state):
//     (b) survivorship-bias foot line,
//     (c) desirable-difficulty note near MINI-MOCK,
//     (d) the reworded abstention-framing foot line ("abstain by design rather
//         than guess").
//   GATED copy ABSENT on fresh/abstained data (the honesty check — no plateau
//   claim / no self-rated caveat when there's nothing real to caveat):
//     (a) "near ceiling ..." (Readiness is abstained),
//     (e) "self-rated · Good/Easy grade" (Performance is abstained).
//   No fabricated numbers; the 5 stats still render in their abstain states;
//   ZERO console errors; ZERO failed /_anki/* POSTs; NO horizontal overflow at
//   360px (the new .hint/.foot lines wrap cleanly).
// Full-page screenshots at both widths are captured for human review.
//
// HONEST SCOPE NOTE: the e2e launcher (qt/tests/launch_anki_for_e2e.py) sets
// ANKI_API_HOST=0.0.0.0, so mediasrv serves the page without the Qt webview
// auth check. This proves render + live abstain data + layout; it does not
// exercise the Qt-GUI-only auth path (verified separately).

import type { ConsoleMessage, Page, Response } from "@playwright/test";

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const MOBILE = { width: 360, height: 800 } as const;
const DESKTOP = { width: 1280, height: 900 } as const;

// Exact copy strings (verbatim from the committed source). CSS uppercases these
// visually, but the DOM textContent preserves original case; we match
// case-insensitively so a rendering tweak to letter-case can't hide a miss.
const STATIC_PRESENT = {
    survivorship: "Pace reflects your run so far — not a promised outcome; results vary.",
    desirableDifficulty: "In-session accuracy may dip — that's the process working.",
    abstentionFraming: "abstain by design rather than guess",
} as const;

const GATED_ABSENT = {
    nearCeiling: "near ceiling · gains slow from here",
    selfRated: "self-rated · Good/Easy grade",
} as const;

function normalize(s: string): string {
    // Collapse whitespace so hard-wrapped source text still matches the rendered
    // (single-run) DOM text node.
    return s.replace(/\s+/g, " ").trim().toLowerCase();
}

function isFailedRpcPost(response: Response): boolean {
    const req = response.request();
    if (req.method() !== "POST") {
        return false;
    }
    if (!new URL(response.url()).pathname.startsWith("/_anki/")) {
        return false;
    }
    return response.status() >= 400;
}

function watchErrors(page: Page): { consoleErrors: string[]; failedRpcs: string[] } {
    const consoleErrors: string[] = [];
    const failedRpcs: string[] = [];
    page.on("console", (msg: ConsoleMessage) => {
        if (msg.type() === "error") {
            consoleErrors.push(msg.text());
        }
    });
    page.on("response", (response: Response) => {
        if (isFailedRpcPost(response)) {
            failedRpcs.push(`${response.status()} ${new URL(response.url()).pathname}`);
        }
    });
    return { consoleErrors, failedRpcs };
}

for (const [label, viewport] of [["mobile", MOBILE], ["desktop", DESKTOP]] as const) {
    test(`LS3 honesty copy present/gated at ${label} (${viewport.width}px)`, async ({ page }) => {
        const { consoleErrors, failedRpcs } = watchErrors(page);

        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto("/speedrun-home", { waitUntil: "networkidle" });

        // Data state loaded (not spinner / error / empty).
        await expect(page.getByRole("heading", { name: "Splits" })).toBeVisible();
        await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);

        // Whole-page normalized text, used for present/absent substring assertions.
        const bodyText = normalize((await page.locator("body").textContent()) ?? "");

        // --- STATIC copy PRESENT (honest in every state) ---
        for (const [key, str] of Object.entries(STATIC_PRESENT)) {
            expect(
                bodyText.includes(normalize(str)),
                `[${label}] static copy "${key}" MISSING from DOM: expected substring «${str}»`,
            ).toBe(true);
        }

        // --- GATED copy ABSENT on fresh/abstained data (the honesty check) ---
        // First prove the pre-condition: Readiness + Performance ARE abstained,
        // else the "absent" assertions would be vacuous.
        const stats = page.locator(".stats .stat");
        await expect(stats).toHaveCount(5);
        const perfVal = (await stats.nth(2).locator(".val").textContent())?.replace(/\s+/g, " ").trim();
        const readyVal = (await stats.nth(3).locator(".val").textContent())?.replace(/\s+/g, " ").trim();
        expect(perfVal, `Performance not in abstain state: "${perfVal}"`).toBe("— abstains");
        expect(readyVal, `Readiness not in abstain state: "${readyVal}"`).toBe("— abstains");

        for (const [key, str] of Object.entries(GATED_ABSENT)) {
            expect(
                bodyText.includes(normalize(str)),
                `[${label}] gated copy "${key}" WRONGLY PRESENT on abstained data: «${str}»`,
            ).toBe(false);
        }

        // --- No fabricated numbers in the abstained stats or the new copy ---
        // Performance + Readiness values are pure "— abstains" (no digits).
        expect(/\d/.test(perfVal ?? ""), `Performance showed a number: "${perfVal}"`).toBe(false);
        expect(/\d/.test(readyVal ?? ""), `Readiness showed a number: "${readyVal}"`).toBe(false);
        // The five stat labels still render (Calibration incl.), all present.
        const labels = (await page.locator(".stats .stat .label").allTextContents()).map((s) => s.trim());
        expect(labels, `stat labels: [${labels.join(" | ")}]`).toEqual([
            "Coverage",
            "Memory · verified",
            "Performance",
            "Readiness · pace",
            "Calibration",
        ]);
        // Calibration also abstains on a fresh deck (no fabricated Brier).
        const calVal = (await stats.nth(4).locator(".val").textContent())?.replace(/\s+/g, " ").trim();
        expect(calVal, `Calibration val: "${calVal}"`).toBe("— abstains");

        // --- No horizontal overflow (esp. at 360px where the foot/hint wrap) ---
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `horizontal overflow at ${viewport.width}px was ${overflow}px (expected <=2)`)
            .toBeLessThanOrEqual(2);

        // --- Zero console errors, zero failed /_anki/* POSTs ---
        expect(consoleErrors, `console errors @${label}: ${consoleErrors.join(" || ")}`)
            .toEqual([]);
        expect(failedRpcs, `failed /_anki/* POSTs @${label}: ${failedRpcs.join(" || ")}`)
            .toEqual([]);

        // --- Full-page screenshot for human review ---
        await page.screenshot({
            path: `${SCRATCH}/ls3-honesty-copy-${viewport.width}.png`,
            fullPage: true,
        });
    });
}
