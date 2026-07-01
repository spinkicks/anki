// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Gate evidence for the Speedrun Home page. A Cursor audit found the page
// shipped BROKEN on desktop (its RPC POSTs 403'd / 404'd, so it rendered the
// error/empty state instead of data). A green build alone does not prove the
// fix. This test drives the real mediasrv-served SvelteKit page with a live
// backend collection and asserts:
//   (a) the four Speedrun RPC routes EXIST and succeed (200, not 404/403),
//   (b) the exam-profile bootstrap works so the page renders DATA (segments),
//       not the "No cards found for this exam profile" error/empty state, and
//   (c) captures a full-page screenshot for human review.
//
// HONEST SCOPE NOTE: the e2e launcher (qt/tests/launch_anki_for_e2e.py) sets
// ANKI_API_HOST=0.0.0.0, which makes mediasrv's _have_api_access() return true
// for every /_anki/* request. That deliberately BYPASSES the Qt
// AuthInterceptor / webview-kind auth check. So this test proves routing +
// profile bootstrap + live render; it does NOT exercise the Qt-GUI-only
// webview-kind 403 fix (that is verified separately by code inspection).

import { expect, test } from "./fixtures";

// Absolute path (forward slashes) for the gate screenshot. Left OUTSIDE the
// repo on purpose so it is not committed.
const SCREENSHOT_PATH =
    "C:/Users/davir/AppData/Local/Temp/claude/C--Users-davir-Ultra-Alpha-Speedrun/01774af5-6bec-4e59-abab-6a571a9cc8bd/scratchpad/speedrun-home-gate.png";

// The Speedrun Home page loads these three RPCs via @speedrun/data (loadHome ->
// loadProfile+loadRows+loadCoverage). getPerformanceReadiness is scaffolding
// that the Home page does NOT call, so we do not require it to have fired, but
// if it ever does we still assert it did not error.
const REQUIRED_METHODS = ["getExamProfile", "getTopicMastery", "getCoverage"] as const;
const ALL_SPEEDRUN_METHODS = [...REQUIRED_METHODS, "getPerformanceReadiness"] as const;

function methodFromPath(path: string): string | null {
    for (const m of ALL_SPEEDRUN_METHODS) {
        if (path.includes(`/_anki/${m}`)) {
            return m;
        }
    }
    return null;
}

test("speedrun-home renders live data (RPCs 200, profile bootstrapped)", async ({ page }) => {
    // 1. Attach the response listener BEFORE navigating so no RPC is missed.
    //    Map method -> array of observed statuses (POST + any preflight).
    const rpcStatuses = new Map<string, number[]>();
    page.on("response", (response) => {
        const method = methodFromPath(new URL(response.url()).pathname);
        if (!method) {
            return;
        }
        // Only count POSTs (the actual RPC calls); ignore OPTIONS preflights.
        if (response.request().method() !== "POST") {
            return;
        }
        const list = rpcStatuses.get(method) ?? [];
        list.push(response.status());
        rpcStatuses.set(method, list);
    });

    // 2. Navigate to the mediasrv-served SvelteKit page and let it settle.
    await page.goto("/speedrun-home", { waitUntil: "networkidle" });

    // 3. Assert every Speedrun RPC that fired returned 200 (not 403 / not 404).
    //    Fail loudly, listing the exact status of every required method.
    const summary = ALL_SPEEDRUN_METHODS.map(
        (m) => `${m}=${(rpcStatuses.get(m) ?? []).join(",") || "<not called>"}`,
    ).join(" | ");

    for (const method of REQUIRED_METHODS) {
        const statuses = rpcStatuses.get(method);
        expect(statuses, `${method} was never POSTed. Observed: ${summary}`).toBeTruthy();
        for (const status of statuses!) {
            expect(status, `${method} returned ${status} (expected 200). Observed: ${summary}`)
                .toBe(200);
        }
    }
    // Any getPerformanceReadiness call that DID fire must also not have errored.
    for (const status of rpcStatuses.get("getPerformanceReadiness") ?? []) {
        expect(status, `getPerformanceReadiness returned ${status}. Observed: ${summary}`)
            .toBe(200);
    }

    // 4. Assert the page rendered DATA, not the error/empty state.
    //    a) The error/empty state text must be ABSENT.
    await expect(page.getByText("No cards found for this exam profile")).toHaveCount(0);
    //    b) The branded wordmark is visible ("SPEED" + amber "RUN"). The Splits
    //       heading is a reliable data-state marker (only rendered when a view
    //       exists).
    await expect(page.getByRole("heading", { name: "Splits" })).toBeVisible();
    await expect(page.locator(".wordmark")).toContainText("SPEED");
    await expect(page.locator(".wordmark")).toContainText("RUN");
    //    c) At least one bootstrapped-profile segment name appears. The default
    //       gre_math profile has top-level topics "Calculus" and "Linear
    //       algebra" (rendered upper-cased via CSS; match case-insensitively on
    //       the DOM text). Segment headers use the .seg class.
    await expect(page.locator("tr.seg")).not.toHaveCount(0);
    const segText = (await page.locator("tr.seg").allTextContents()).join(" ");
    expect(
        /calculus/i.test(segText) || /linear algebra/i.test(segText),
        `expected a bootstrapped segment name (Calculus / Linear algebra) in: ${segText}`,
    ).toBeTruthy();
    //    d) On the fresh e2e collection the leaf rows are in the honest abstain
    //       state ("NOT TIMED — review N more"). Assert at least one abstain row
    //       OR (fallback) a timed split exists — either proves live leaf data
    //       rendered, not a blank table.
    const abstainRows = page.locator("tr.abstain");
    const timedRows = page.locator("tr.row:not(.abstain)");
    const abstainCount = await abstainRows.count();
    const timedCount = await timedRows.count();
    expect(
        abstainCount + timedCount,
        `expected at least one leaf split row (abstain=${abstainCount} timed=${timedCount})`,
    ).toBeGreaterThan(0);

    // 5. Capture the full-page gate screenshot to the absolute scratchpad path.
    await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
});
