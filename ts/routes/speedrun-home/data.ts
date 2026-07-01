// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Home-specific view assembly built ON TOP of the shared helpers in
// @speedrun/data. This file does NOT talk to the backend directly beyond
// composing the shared loaders; it shapes their output into the view model the
// Home page renders (segments + honest headline stats).
import { type ExamProfile, loadCoverage, loadProfile, loadRows, type Row } from "@speedrun/data";

// A segment is a container topic (ets_weight === 0) holding its leaf rows.
export interface Segment {
    num: string; // "01", "02", ... in descending ETS-weight order
    name: string;
    weightPct: number; // sum of leaf ets_weight within the segment, as a percent
    rows: Row[];
}

export interface HomeView {
    profile: ExamProfile;
    coverage: { covered: number; total: number; percent: number };
    segments: Segment[];
    // memoryVerified.timed = leaf rows we have actually timed (non-abstained).
    // memoryVerified.total = leaf rows that have ANY review data
    //   (cardsWithData > 0). This is the honest reading: the "/timed"
    //   denominator is "topics you've started studying", not "all topics in the
    //   profile" — abstaining on an untouched topic isn't a failure to time it,
    //   there's simply nothing to time yet. Meter = timed/total.
    memoryVerified: { timed: number; total: number };
    // weakestTimed = label of the lowest-avgRecall NON-abstained leaf (drives
    // the NEXT SEGMENT hint). null when nothing has been timed yet.
    weakestTimed: string | null;
    // timedReviewsTotal = sum of gradedReviews across leaves; drives the honest
    // run status (0 => NO RUN YET; else RUN ACTIVE + reviews-logged line).
    timedReviewsTotal: number;
}

export async function loadHome(examId = "gre_math"): Promise<HomeView | null> {
    const profile = await loadProfile(examId);
    if (!profile) {
        return null;
    }
    const [rows, coverage] = await Promise.all([
        loadRows(profile),
        loadCoverage(profile),
    ]);

    const containers = rows.filter((r) => r.isContainer);
    const leaves = rows.filter((r) => !r.isContainer);

    // Segments = containers ordered by descending ETS weight. Container weight
    // is ets_weight === 0 by definition, so rank by the summed leaf weight of
    // each segment (the legitimate ordering from the exam DAG).
    const segLeaves = (c: Row) => leaves.filter((r) => r.root === c.id);
    const segWeight = (c: Row) => segLeaves(c).reduce((acc, r) => acc + r.weight, 0);

    const ordered = [...containers].sort((a, b) => segWeight(b) - segWeight(a));
    const segments: Segment[] = ordered.map((c, i) => ({
        num: String(i + 1).padStart(2, "0"),
        name: c.label,
        weightPct: Math.round(segWeight(c) * 100),
        rows: segLeaves(c),
    }));

    const timedLeaves = leaves.filter((r) => !r.abstained);
    const withData = leaves.filter((r) => r.cardsWithData > 0);

    const memoryVerified = {
        timed: timedLeaves.length,
        total: withData.length,
    };

    // weakest timed = lowest avgRecall among non-abstained leaves.
    let weakestTimed: string | null = null;
    if (timedLeaves.length > 0) {
        const weakest = timedLeaves.reduce((lo, r) => r.avgRecall < lo.avgRecall ? r : lo);
        weakestTimed = weakest.label;
    }

    const timedReviewsTotal = leaves.reduce((acc, r) => acc + r.gradedReviews, 0);

    return {
        profile,
        coverage,
        segments,
        memoryVerified,
        weakestTimed,
        timedReviewsTotal,
    };
}
