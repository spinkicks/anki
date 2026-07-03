// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// TEMPORARY UI-verification gate for the new 5th Home stat "Calibration".
// Leave this file UNSTAGED (the controller does not commit it). It drives the
// real mediasrv-served SvelteKit Home page against a live FRESH e2e collection
// (0 logged calibration attempts => the engine's GetCalibration RPC abstains,
// threshold = 20) at mobile (360px) and desktop (1280px) and asserts:
//   (a) the Calibration stat is PRESENT as the 5th stat, after Readiness,
//   (b) it renders the ABSTAIN state ("— abstains" + empty meter, no fabricated
//       Brier number) exactly like the Readiness abstain block,
//   (c) it reuses the shared .stat/.label/.val/.meter structure (computed-style
//       spot check vs the Performance stat — no broken/overflowing layout),
//   (d) the other 4 stats (Coverage, Memory·verified, Performance, Readiness)
//       still render (no regression),
//   (e) ZERO console errors, ZERO failed /_anki/* POSTs (incl. getCalibration),
//       and NO horizontal overflow at 360px.
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

// The five headline stats, in DOM order. Calibration is the new 5th cell.
const STAT_LABELS = [
    "Coverage",
    "Memory · verified",
    "Performance",
    "Readiness · pace",
    "Calibration",
] as const;

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
    test(`Calibration stat renders (abstain) at ${label} (${viewport.width}px)`, async ({ page }) => {
        const { consoleErrors, failedRpcs } = watchErrors(page);

        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto("/speedrun-home", { waitUntil: "networkidle" });

        // Data state loaded (not spinner / error / empty).
        await expect(page.getByRole("heading", { name: "Splits" })).toBeVisible();
        await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);

        // 1. Exactly five stats, in the expected order (Calibration is 5th).
        const stats = page.locator(".stats .stat");
        await expect(stats).toHaveCount(5);
        const labels = await page.locator(".stats .stat .label").allTextContents();
        expect(
            labels.map((s) => s.trim()),
            `stat labels/order mismatch: got [${labels.join(" | ")}]`,
        ).toEqual([...STAT_LABELS]);

        // 2. The Calibration stat is the LAST (5th) stat and renders the abstain
        //    state: ".val.muted" with "—" + "abstains", and an EMPTY meter.
        const cal = stats.nth(4);
        await expect(cal.locator(".label")).toHaveText("Calibration");
        const calVal = cal.locator(".val");
        await expect(calVal).toHaveClass(/muted/);
        const calValText = (await calVal.textContent())?.replace(/\s+/g, " ").trim();
        expect(calValText, `Calibration val text was "${calValText}"`).toBe("— abstains");
        // No fabricated Brier number on empty data (no digits in the value).
        expect(/\d/.test(calValText ?? ""), `Calibration showed a number: "${calValText}"`)
            .toBe(false);
        // Empty meter: the fill <i> has width 0% and 0 rendered pixels.
        const calFill = cal.locator(".meter i");
        await expect(calFill).toHaveCount(1);
        const calFillWidth = await calFill.evaluate((el) => (el as HTMLElement).getBoundingClientRect().width);
        expect(calFillWidth, `Calibration meter fill width was ${calFillWidth}px (expected 0)`)
            .toBeLessThanOrEqual(0.5);
        // Abstain branch renders NO hint (the "self-rated" gap hint is scored-only).
        await expect(cal.locator(".hint")).toHaveCount(0);

        // 3. The abstain block mirrors the Readiness abstain block verbatim: same
        //    "— abstains" muted value shape. Readiness is the 4th stat.
        const readinessVal = stats.nth(3).locator(".val");
        await expect(readinessVal).toHaveClass(/muted/);
        const readinessValText = (await readinessVal.textContent())?.replace(/\s+/g, " ").trim();
        expect(readinessValText, `Readiness val text was "${readinessValText}"`).toBe("— abstains");

        // 4. Structural / computed-style spot check: the Calibration cell reuses
        //    the exact same .stat/.label/.val classes as the Performance cell —
        //    matching fontFamily/textTransform/letterSpacing on label & value.
        //    Proves NO new CSS regression / broken layout.
        const perf = stats.nth(2); // Performance
        const styleOf = (loc: ReturnType<typeof page.locator>, props: string[]) =>
            loc.evaluate((el, ps) => {
                const cs = getComputedStyle(el as HTMLElement);
                return Object.fromEntries(ps.map((p) => [p, cs.getPropertyValue(p)]));
            }, props);
        const labelProps = ["font-family", "font-size", "letter-spacing", "text-transform", "color"];
        const perfLabelStyle = await styleOf(perf.locator(".label"), labelProps);
        const calLabelStyle = await styleOf(cal.locator(".label"), labelProps);
        expect(calLabelStyle, `label style drift vs Performance: ${JSON.stringify(calLabelStyle)}`)
            .toEqual(perfLabelStyle);
        const valProps = ["font-family", "font-size", "font-weight", "text-transform"];
        const perfValStyle = await styleOf(perf.locator(".val"), valProps);
        const calValStyle = await styleOf(cal.locator(".val"), valProps);
        expect(calValStyle, `val style drift vs Performance: ${JSON.stringify(calValStyle)}`)
            .toEqual(perfValStyle);
        // Meter element exists with the shared 6px height (shared .meter class).
        const calMeterH = await cal.locator(".meter").evaluate(
            (el) => getComputedStyle(el as HTMLElement).height,
        );
        expect(calMeterH, `Calibration meter height was "${calMeterH}"`).toBe("6px");

        // 5. The other four stats still render their expected non-broken content
        //    (Coverage/Memory show real numbers; Performance abstains on fresh).
        await expect(stats.nth(0).locator(".val")).toContainText("topics");
        await expect(stats.nth(1).locator(".val")).toContainText("timed");
        const perfValText = (await perf.locator(".val").textContent())?.replace(/\s+/g, " ").trim();
        expect(perfValText, `Performance val text was "${perfValText}"`).toBe("— abstains");

        // 6. No horizontal overflow (esp. at 360px where the 5 stats stack).
        const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `horizontal overflow at ${viewport.width}px was ${overflow}px (expected <=2)`)
            .toBeLessThanOrEqual(2);

        // 7. Zero console errors, zero failed /_anki/* POSTs (incl. getCalibration).
        expect(consoleErrors, `console errors @${label}: ${consoleErrors.join(" || ")}`)
            .toEqual([]);
        expect(failedRpcs, `failed /_anki/* POSTs @${label}: ${failedRpcs.join(" || ")}`)
            .toEqual([]);

        // 8. Full-page screenshot for human review.
        await page.screenshot({
            path: `${SCRATCH}/calibration-stat-${viewport.width}.png`,
            fullPage: true,
        });
    });
}
