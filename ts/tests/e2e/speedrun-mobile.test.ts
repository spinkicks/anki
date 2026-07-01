// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Gate evidence for Phase M0 (mobile-first responsive). The M0 CSS makes both
// shared Speedrun pages (Home + Memory) stack into single-column cards at
// <=768px and restores the desktop columns above that breakpoint. A green build
// does not prove the pages actually fit a phone. This test drives the real
// mediasrv-served SvelteKit pages with a live backend collection and, for each
// page at BOTH mobile (360px) and desktop (1280px) widths, asserts:
//   (a) the page rendered DATA (not the "No cards found" error/empty state),
//   (b) at mobile width the layout does NOT overflow horizontally
//       (scrollWidth - innerWidth <= 2px), the key mobile-fitness check, and
//   (c) captures a full-page screenshot for human review.
//
// HONEST SCOPE NOTE: the e2e launcher (qt/tests/launch_anki_for_e2e.py) sets
// ANKI_API_HOST=0.0.0.0, so mediasrv serves the pages without the Qt webview
// auth check. This test proves responsive layout + live render; it does not
// exercise the Qt-GUI-only auth path (verified separately).

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const MOBILE = { width: 360, height: 800 } as const;
const DESKTOP = { width: 1280, height: 900 } as const;

// Each page: route, a heading that only renders in the data state, and the
// screenshot basenames for the mobile / desktop captures.
const PAGES = [
    {
        name: "home",
        route: "/speedrun-home",
        // The "Splits" heading + the SPEED/RUN wordmark only render once a view
        // exists (i.e. data loaded, not the error/empty state).
        readyHeading: "Splits",
        mobileShot: `${SCRATCH}/m0-home-360.png`,
        desktopShot: `${SCRATCH}/m0-home-desktop.png`,
    },
    {
        name: "memory",
        route: "/speedrun-memory",
        readyHeading: "Memory",
        mobileShot: `${SCRATCH}/m0-memory-360.png`,
        desktopShot: `${SCRATCH}/m0-memory-desktop.png`,
    },
] as const;

for (const pg of PAGES) {
    for (const [label, viewport] of [["mobile", MOBILE], ["desktop", DESKTOP]] as const) {
        test(`speedrun-${pg.name} renders data at ${label} (${viewport.width}px)`, async ({ page }) => {
            // 1. Set the viewport BEFORE navigating so the page lays out for the
            //    target width from the first render.
            await page.setViewportSize({ width: viewport.width, height: viewport.height });

            // 2. Navigate to the mediasrv-served SvelteKit page and let it settle.
            await page.goto(pg.route, { waitUntil: "networkidle" });

            // 3. Wait for the data-state heading to render.
            await expect(page.getByRole("heading", { name: pg.readyHeading })).toBeVisible();

            // 4. Assert DATA rendered, not the error/empty state.
            await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);
            if (pg.name === "home") {
                // Branded wordmark + at least one bootstrapped segment header.
                await expect(page.locator(".wordmark")).toContainText("SPEED");
                await expect(page.locator(".wordmark")).toContainText("RUN");
                await expect(page.locator("tr.seg")).not.toHaveCount(0);
                const segText = (await page.locator("tr.seg").allTextContents()).join(" ");
                expect(
                    /calculus/i.test(segText) || /linear algebra/i.test(segText),
                    `expected a bootstrapped segment name (Calculus / Linear algebra) in: ${segText}`,
                ).toBeTruthy();
            } else {
                // Memory: group headers carry the bootstrapped container labels.
                await expect(page.locator("tr.grouphdr")).not.toHaveCount(0);
                const grpText = (await page.locator("tr.grouphdr").allTextContents()).join(" ");
                expect(
                    /calculus/i.test(grpText) || /linear algebra/i.test(grpText),
                    `expected a bootstrapped topic label (Calculus / Linear algebra) in: ${grpText}`,
                ).toBeTruthy();
            }

            // 5. At MOBILE width, assert NO horizontal overflow. This is the key
            //    mobile-fitness check: nothing spills past the 360px viewport.
            if (label === "mobile") {
                const overflow = await page.evaluate(
                    () => document.documentElement.scrollWidth - window.innerWidth,
                );
                expect(
                    overflow,
                    `horizontal overflow on ${pg.name} at ${viewport.width}px was ${overflow}px (expected <=2)`,
                ).toBeLessThanOrEqual(2);
            }

            // 6. Full-page screenshot for human review.
            await page.screenshot({
                path: label === "mobile" ? pg.mobileShot : pg.desktopShot,
                fullPage: true,
            });
        });
    }
}
