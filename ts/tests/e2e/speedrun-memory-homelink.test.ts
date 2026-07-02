// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Gate evidence for the "‹ HOME" back affordance added to the shared Speedrun
// Memory page (ts/routes/speedrun-memory/MemoryDashboard.svelte). It mirrors
// Home's existing forward link `<a href="/speedrun-memory">MEMORY ▸</a>` — same
// SvelteKit client-side route — so clicking "‹ HOME" on the Memory page must
// navigate the SAME webview back to Home. Both desktop (Qt webview) and Android
// (PageFragment webview) load these as SvelteKit pages, so the anchor works on
// both with zero native code. This test drives the real mediasrv-served page
// with a live backend collection and, at BOTH mobile (360px) and desktop
// (1280px), asserts:
//   (2a) the "‹ HOME" link is PRESENT, styled as a muted uppercase back
//        affordance (color token --muted, letter-spacing 0.18em, positioned
//        top-left of the header above the "Memory" title),
//   (2b) href resolves to /speedrun-home AND clicking it client-routes the
//        webview to Home (URL becomes /speedrun-home and Home content renders —
//        the RunHeader "START RUN" appears),
//   (2c) NO regression to the Memory table: all 7 columns incl. "GAP (Δ)"
//        render; the header/Refresh/"Weakest first" controls persist,
//   (2d) ZERO console errors, ZERO failed /_anki/* POSTs, no horizontal
//        overflow at 360px,
//   (2e) NO fabricated numbers: on the fresh e2e collection every score cell
//        abstains ("—" / unlock copy), never a made-up number,
// and captures a full-page screenshot of each width for human review.
//
// HONEST SCOPE NOTE: the e2e launcher (qt/tests/launch_anki_for_e2e.py) sets
// ANKI_API_HOST=0.0.0.0, so mediasrv serves the pages without the Qt webview
// auth check. This proves render + data + client-side nav; it does not exercise
// the Qt-GUI-only auth path (verified separately by code inspection).

import type { ConsoleMessage, Page, Response } from "@playwright/test";

import { expect, test } from "./fixtures";

const SCRATCH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad";

const MOBILE = { width: 360, height: 800 } as const;
const DESKTOP = { width: 1280, height: 900 } as const;

// A failed Speedrun RPC = a POST to /_anki/* that returned >= 400.
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
    test(`speedrun-memory "‹ HOME" back link: present, styled, routes to Home at ${label} (${viewport.width}px)`, async ({ page }) => {
        const { consoleErrors, failedRpcs } = watchErrors(page);

        // Lay out for the target width from the first render.
        await page.setViewportSize({ width: viewport.width, height: viewport.height });

        // 1. Navigate to the Memory page and wait for the data state.
        await page.goto("/speedrun-memory", { waitUntil: "networkidle" });
        await expect(page.getByRole("heading", { name: "Memory" })).toBeVisible();
        await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);

        // ---- 2a. The "‹ HOME" affordance is PRESENT and styled ----
        const homeLink = page.locator("a.home-link");
        await expect(homeLink).toBeVisible();
        // Visible text is "‹ HOME" (the chevron + label).
        await expect(homeLink).toHaveText(/‹\s*HOME/);

        // Computed styles: muted color token (#7c8794 => rgb(124,135,148)),
        // uppercase (via text-transform, applied to "home" source text), and the
        // 0.18em tracking. font-size is 11px so 0.18em = 1.98px.
        const linkStyles = await homeLink.evaluate((el) => {
            const cs = getComputedStyle(el as HTMLElement);
            return {
                color: cs.color,
                textTransform: cs.textTransform,
                letterSpacing: cs.letterSpacing,
                textDecorationLine: cs.textDecorationLine,
                fontSize: cs.fontSize,
                minHeight: cs.minHeight,
                display: cs.display,
            };
        });
        // Muted color token — rgb(124, 135, 148).
        expect(linkStyles.color, `home-link color was ${linkStyles.color}`).toBe(
            "rgb(124, 135, 148)",
        );
        expect(linkStyles.textTransform).toBe("uppercase");
        // 0.18em * 11px = 1.98px (browser rounds; accept ~1.98px).
        expect(
            parseFloat(linkStyles.letterSpacing),
            `letter-spacing was ${linkStyles.letterSpacing}`,
        ).toBeGreaterThan(1.5);
        expect(linkStyles.textDecorationLine).toBe("none");
        // Mobile: >=44px touch target; desktop: min-height collapses to 0.
        if (label === "mobile") {
            expect(
                parseFloat(linkStyles.minHeight),
                `mobile min-height was ${linkStyles.minHeight} (expected >=44)`,
            ).toBeGreaterThanOrEqual(44);
        }

        // Positioned top-left of the header, ABOVE the .titlebar (Memory title).
        const layout = await page.evaluate(() => {
            const link = document.querySelector("a.home-link") as HTMLElement | null;
            const titlebar = document.querySelector(".memory header .titlebar") as HTMLElement | null;
            const header = document.querySelector(".memory header") as HTMLElement | null;
            if (!link || !titlebar || !header) {
                return null;
            }
            const l = link.getBoundingClientRect();
            const t = titlebar.getBoundingClientRect();
            const h = header.getBoundingClientRect();
            return {
                linkTop: l.top,
                linkLeft: l.left,
                titlebarTop: t.top,
                headerLeft: h.left,
                // Is the link the header's first element child?
                firstChildIsLink: header.firstElementChild === link,
            };
        });
        expect(layout, "could not resolve header/link/titlebar layout").not.toBeNull();
        // Above the title (its top is <= the titlebar's top).
        expect(
            layout!.linkTop,
            `home-link top ${layout!.linkTop} should be above titlebar top ${layout!.titlebarTop}`,
        ).toBeLessThanOrEqual(layout!.titlebarTop + 1);
        // Left-aligned within the header (allow the header's own padding slack).
        expect(
            layout!.linkLeft - layout!.headerLeft,
            `home-link left offset from header was ${layout!.linkLeft - layout!.headerLeft}px`,
        ).toBeLessThanOrEqual(20);
        // It is the first child of <header> (deliberate back affordance placement).
        expect(layout!.firstChildIsLink, "home-link must be the header's first child").toBe(true);

        // ---- 2c. NO regression to the Memory table (assert BEFORE navigating away) ----
        // Desktop: the thead is shown with all 7 columns; mobile hides thead via
        // CSS (display:none) but the <th> elements still exist in the DOM.
        const headers = await page.locator(".memory table thead th").allTextContents();
        expect(headers.length, `expected 7 header columns, got ${headers.length}: ${headers}`)
            .toBe(7);
        const headerJoined = headers.join(" | ");
        for (const col of ["TOPIC", "RECALL", "RANGE", "DATA", "PERFORMANCE", "READINESS", "GAP"]) {
            expect(headerJoined.toUpperCase()).toContain(col);
        }
        // The "GAP (Δ)" column specifically.
        expect(headerJoined).toMatch(/GAP\s*\(Δ\)/);
        // Refresh button + "Weakest first" checkbox present.
        await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
        await expect(page.locator("label.sort input[type=checkbox]")).toBeVisible();

        // ---- 2e. NO fabricated numbers on the fresh collection ----
        // Every leaf row must be in the honest abstain state: recall cell "—"
        // and the unlock copy. Assert there is at least one leaf row and that
        // NONE of them render a numeric recall percentage.
        const leafRows = page.locator(".memory tbody tr:not(.grouphdr)");
        const leafCount = await leafRows.count();
        expect(leafCount, "expected at least one memory leaf row").toBeGreaterThan(0);
        // Abstained rows carry the .abstained class + render "—" in RECALL.
        const abstainedCount = await page.locator(
            ".memory tbody tr:not(.grouphdr).abstained",
        ).count();
        expect(
            abstainedCount,
            `expected all ${leafCount} leaf rows to abstain on fresh data; ${abstainedCount} did`,
        ).toBe(leafCount);
        // The RECALL cells must be "—" (never a fabricated %). Also assert the
        // GAP cells abstain ("—") since Performance is not real yet.
        const recallCells = await page.locator(".memory tbody td.recall").allTextContents();
        for (const c of recallCells) {
            expect(c.trim(), `RECALL cell "${c}" must abstain, not show a number`).toBe("—");
        }
        const gapCells = await page.locator(".memory tbody td.c-gap").allTextContents();
        for (const c of gapCells) {
            expect(c.trim(), `GAP cell "${c}" must abstain (—) on fresh data`).toBe("—");
        }

        // ---- 2b. href + client-side navigation to Home ----
        await expect(homeLink).toHaveAttribute("href", "/speedrun-home");
        // Resolved absolute href points at the /speedrun-home route.
        const resolvedHref = await homeLink.evaluate((el) => (el as HTMLAnchorElement).href);
        expect(resolvedHref).toContain("/speedrun-home");

        // Screenshot the Memory page (with the back affordance) BEFORE clicking.
        await page.screenshot({
            path: `${SCRATCH}/homelink-memory-${label}.png`,
            fullPage: true,
        });

        // Click the back link. This must client-route the SAME page to Home.
        await homeLink.click();
        await page.waitForURL(/\/speedrun-home\/?$/, { timeout: 15_000 });
        expect(page.url()).toMatch(/\/speedrun-home\/?$/);

        // Home content must render: the RunHeader with the START RUN button, plus
        // the branded wordmark — proving we actually landed on Home, not a 404.
        await expect(page.locator("button.run")).toBeVisible();
        await expect(page.locator("button.run")).toHaveText(/START RUN/i);
        await expect(page.locator(".wordmark")).toContainText("SPEED");
        await expect(page.locator(".wordmark")).toContainText("RUN");
        await expect(page.getByRole("heading", { name: "Splits" })).toBeVisible();

        // Screenshot the resulting Home page for review.
        await page.screenshot({
            path: `${SCRATCH}/homelink-home-after-click-${label}.png`,
            fullPage: true,
        });

        // ---- 2d. Health: no console errors, no failed RPC POSTs, no overflow ----
        // (Overflow is measured on the Memory page state; re-navigate back so the
        //  360px overflow check reflects the page under test.)
        if (label === "mobile") {
            await page.goto("/speedrun-memory", { waitUntil: "networkidle" });
            await expect(page.getByRole("heading", { name: "Memory" })).toBeVisible();
            const overflow = await page.evaluate(
                () => document.documentElement.scrollWidth - window.innerWidth,
            );
            expect(
                overflow,
                `horizontal overflow on memory@${label} was ${overflow}px (expected <=2)`,
            ).toBeLessThanOrEqual(2);
        }

        expect(
            consoleErrors,
            `console errors on memory-homelink@${label}: ${consoleErrors.join(" || ")}`,
        ).toEqual([]);
        expect(
            failedRpcs,
            `failed /_anki/* POSTs on memory-homelink@${label}: ${failedRpcs.join(" || ")}`,
        ).toEqual([]);
    });
}
