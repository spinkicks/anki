// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Live UI smoke test for the two Speedrun pages ("The Run"). This is the
// "open the app as a real window and use it" pass: for BOTH speedrun-home and
// speedrun-memory, at mobile (360px) and desktop (1280px), it drives the real
// mediasrv-served SvelteKit page against a live backend collection and asserts
// the page is healthy end-to-end:
//   (a) ZERO console errors and ZERO failed /_anki/* RPC POSTs (>=400),
//   (b) no horizontal overflow (scrollWidth - innerWidth <= 2px),
//   (c) the page renders DARK ("The Run" palette #0B0E12) at runtime — proving
//       Memory's dark re-theme actually rendered, matching Home, and
//   (d) core interactions (Home: sort toggle + START RUN; Memory: "Weakest
//       first" checkbox) run without throwing / logging an error.
// Full-page screenshots for both pages at both widths are captured for review.
//
// HONEST SCOPE NOTE: the e2e launcher (qt/tests/launch_anki_for_e2e.py) sets
// ANKI_API_HOST=0.0.0.0, so mediasrv's _have_api_access() returns true for
// every /_anki/* request, deliberately BYPASSING the Qt AuthInterceptor /
// webview-kind auth check. So this proves render + data + interaction +
// dark-theme; it does NOT exercise the Qt-GUI-only webview-kind 403 path (that
// fix is verified separately by code inspection).

import type { ConsoleMessage, Page, Response } from "@playwright/test";

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const MOBILE = { width: 360, height: 800 } as const;
const DESKTOP = { width: 1280, height: 900 } as const;

// A channel is "dark" when every RGB component is below this threshold. The
// pages use --ink #0B0E12 (11, 14, 18) as the page background; a light/near-
// white background (e.g. rgb(255,255,255)) would blow well past 40.
const DARK_MAX_CHANNEL = 40;

interface PageSpec {
    readonly name: "home" | "memory";
    readonly route: string;
    // A heading that only renders in the loaded data state (not spinner/empty).
    readonly readyHeading: string;
    // The root element whose computed background must be dark.
    readonly rootSelector: string;
    readonly mobileShot: string;
    readonly desktopShot: string;
}

const PAGES: readonly PageSpec[] = [
    {
        name: "home",
        route: "/speedrun-home",
        readyHeading: "Splits",
        rootSelector: ".app",
        mobileShot: `${SCRATCH}/ui-home-360.png`,
        desktopShot: `${SCRATCH}/ui-home-desktop.png`,
    },
    {
        name: "memory",
        route: "/speedrun-memory",
        readyHeading: "Memory",
        rootSelector: ".memory",
        mobileShot: `${SCRATCH}/ui-memory-360.png`,
        desktopShot: `${SCRATCH}/ui-memory-desktop.png`,
    },
];

// Parse a computed "rgb(r, g, b)" / "rgba(r, g, b, a)" string into channels.
// Returns null if it cannot be parsed (e.g. "transparent").
function parseRgb(color: string): { r: number; g: number; b: number } | null {
    const m = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (!m) {
        return null;
    }
    return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]) };
}

// A failed Speedrun RPC = a POST to /_anki/* that returned >= 400. Benign
// non-POST GET 404 fallback probes (SvelteKit asset/route probing) are ignored.
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

// Attach console-error and failed-RPC listeners to `page` BEFORE navigation.
// Returns arrays that fill in as events fire, plus a formatter for messages.
function watchErrors(page: Page): {
    consoleErrors: string[];
    failedRpcs: string[];
} {
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

for (const pg of PAGES) {
    for (const [label, viewport] of [["mobile", MOBILE], ["desktop", DESKTOP]] as const) {
        test(`speedrun-${pg.name} UI smoke at ${label} (${viewport.width}px)`, async ({ page }) => {
            // 1. Register listeners BEFORE navigating so nothing is missed.
            const { consoleErrors, failedRpcs } = watchErrors(page);

            // Set the viewport before navigating so the page lays out for the
            // target width from the first render.
            await page.setViewportSize({ width: viewport.width, height: viewport.height });

            // 2. Navigate and wait for the network to settle + the data-state
            //    heading to render (proves data loaded, not spinner/empty).
            await page.goto(pg.route, { waitUntil: "networkidle" });
            await expect(page.getByRole("heading", { name: pg.readyHeading })).toBeVisible();
            await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);

            // 3a. Zero console errors.
            expect(
                consoleErrors,
                `console errors on ${pg.name}@${label}: ${consoleErrors.join(" || ")}`,
            ).toEqual([]);
            // 3b. Zero failed /_anki/* POSTs.
            expect(
                failedRpcs,
                `failed /_anki/* POSTs on ${pg.name}@${label}: ${failedRpcs.join(" || ")}`,
            ).toEqual([]);

            // 3c. No horizontal overflow.
            const overflow = await page.evaluate(
                () => document.documentElement.scrollWidth - window.innerWidth,
            );
            expect(
                overflow,
                `horizontal overflow on ${pg.name}@${label} was ${overflow}px (expected <=2)`,
            ).toBeLessThanOrEqual(2);

            // 4. Verify the page renders DARK at runtime (proves Memory's dark
            //    re-theme rendered; same sanity check on Home's .app).
            const bg = await page.evaluate((sel) => {
                const el = document.querySelector(sel);
                return el ? getComputedStyle(el).backgroundColor : "";
            }, pg.rootSelector);
            const rgb = parseRgb(bg);
            expect(rgb, `could not parse ${pg.rootSelector} background "${bg}" on ${pg.name}`)
                .not.toBeNull();
            expect(
                rgb!.r < DARK_MAX_CHANNEL && rgb!.g < DARK_MAX_CHANNEL && rgb!.b < DARK_MAX_CHANNEL,
                `${pg.rootSelector} background "${bg}" on ${pg.name}@${label} is not dark `
                    + `(each channel must be < ${DARK_MAX_CHANNEL})`,
            ).toBe(true);

            // 5. Interactions — assert no console error / thrown JS error.
            if (pg.name === "home") {
                // 5a. Click the SORT ▾ WEIGHT control; page must still render.
                const sort = page.locator("button.sort");
                await expect(sort).toBeVisible();
                await sort.click();
                await expect(sort).toBeVisible();
                await expect(page.getByRole("heading", { name: "Splits" })).toBeVisible();

                // 5b. Click START RUN. Its default handler guards pycmd, which
                //     is absent outside a Qt webview, so this must be a safe
                //     no-op (no thrown JS error). We assert the click resolves
                //     and the page is still alive.
                const run = page.locator("button.run");
                await expect(run).toBeVisible();
                await run.click();
                await expect(run).toBeVisible();
            } else {
                // 5c. Toggle "Weakest first"; rows must re-render without error.
                const rows = page.locator(".memory tbody tr:not(.grouphdr)");
                const before = await rows.count();
                expect(before, "expected at least one memory leaf row before toggle")
                    .toBeGreaterThan(0);

                const weakest = page.locator("label.sort input[type=checkbox]");
                await expect(weakest).toBeVisible();
                await weakest.check();
                await expect(weakest).toBeChecked();

                // Re-rendered table still has the same leaf rows present.
                await expect(rows).toHaveCount(before);
            }

            // After interacting, re-assert no console errors / failed RPCs were
            // triggered by the interactions above.
            expect(
                consoleErrors,
                `console errors after interaction on ${pg.name}@${label}: `
                    + consoleErrors.join(" || "),
            ).toEqual([]);
            expect(
                failedRpcs,
                `failed /_anki/* POSTs after interaction on ${pg.name}@${label}: `
                    + failedRpcs.join(" || "),
            ).toEqual([]);

            // 6. Full-page screenshot for human review.
            await page.screenshot({
                path: label === "mobile" ? pg.mobileShot : pg.desktopShot,
                fullPage: true,
            });
        });
    }
}
