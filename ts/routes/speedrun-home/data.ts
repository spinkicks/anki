// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Home-specific view assembly built ON TOP of the shared helpers in
// @speedrun/data. This file does NOT talk to the backend directly beyond
// composing the shared loaders; it shapes their output into the view model the
// Home page renders (segments + honest headline stats).
import {
    type CalibrationHeadline as CalibrationData,
    type ExamProfile,
    GRE_MAX,
    GRE_MIN,
    loadCalibration,
    loadCoverage,
    loadProfile,
    loadRows,
    loadScaffoldSummary,
    type Row,
    type ScoreScale,
    type UnlockHint,
} from "@speedrun/data";

// A segment is a container topic (ets_weight === 0) holding its leaf rows.
export interface Segment {
    num: string; // "01", "02", ... in descending ETS-weight order
    name: string;
    weightPct: number; // sum of leaf ets_weight within the segment, as a percent
    rows: Row[];
}

// Honest headline Performance: ETS-weighted average of per-topic non-abstained
// Performance points (0..1). Abstains until ANY topic has real problem data —
// never a fabricated aggregate over topics we haven't timed.
export interface PerformanceHeadline {
    abstained: boolean;
    // Weighted-average accuracy in 0..1 (0 when abstained). meterPct = pct.
    pct: number;
    // How many topics contributed a real Performance number (for the sub-label).
    timedTopics: number;
}

// Honest headline Readiness: the engine's exam-level 200–990 score, or the
// abstain reason + top unlock hint when it locks. Never a guessed number.
export interface ReadinessHeadline {
    abstained: boolean;
    point: number; // 200–990 (0 when abstained)
    lower: number;
    upper: number;
    percentile: number;
    meterPct: number; // point normalized to the 200–990 track, 0..100
    reason: string; // abstain reason ("" when scored)
    unlockHuman: string; // top unlock hint ("" when none/scored)
    // §7a diminishing-returns flag: true ONLY when Readiness is real (not
    // abstained) AND sits near the top of the 200–990 band. Gates an honest
    // "gains slow near the ceiling" note — never rendered on abstained/empty
    // state, so it can't fabricate a plateau claim on a fresh deck.
    nearCeiling: boolean;
}

// Diminishing-returns threshold: within the top of the GRE 200–990 band. At/above
// this the marginal score gain per unit of study shrinks, so we flag it honestly.
// 940 ≈ the top ~6% of the scale (meterPct ≈ 94%).
export const READINESS_CEILING = 940;

// Honest headline Calibration of the learner's SELF-RATED accuracy. `brier`
// (lower is better) is the primary number; `gapPct` is the ECE reliability gap
// (percentage points) shown as a sub-hint. Abstains below the engine threshold —
// never a fabricated number.
export interface CalibrationHeadline {
    abstained: boolean;
    brier: number; // 0..1, lower is better (0 when abstained)
    gapPct: number; // ECE * 100, the reliability gap in percentage points
    attempts: number; // logged attempts scored (for the sub-label)
}

export interface HomeView {
    profile: ExamProfile;
    coverage: { covered: number; total: number; percent: number };
    segments: Segment[];
    performance: PerformanceHeadline;
    readiness: ReadinessHeadline;
    // Calibration of self-rated accuracy (Brier + reliability gap; abstains).
    calibration: CalibrationHeadline;
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
    const [rows, coverage, scaffold, calibrationData] = await Promise.all([
        loadRows(profile),
        loadCoverage(profile),
        loadScaffoldSummary(profile),
        loadCalibration(profile),
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

    const performance = buildPerformanceHeadline(leaves, scaffold.rows);
    const readiness = buildReadinessHeadline(
        scaffold.overallReadiness,
        scaffold.abstainReason,
        scaffold.unlockRequirements,
    );
    const calibration = buildCalibrationHeadline(calibrationData);

    return {
        profile,
        coverage,
        segments,
        performance,
        readiness,
        calibration,
        memoryVerified,
        weakestTimed,
        timedReviewsTotal,
    };
}

// Minimal structural shapes so the headline builders stay unit-testable without
// importing the full ScaffoldCell type surface. (mirrors @speedrun/data)
interface CellLike {
    abstained: boolean;
    point: number;
    lower: number;
    upper: number;
    percentile: number;
    scale: ScoreScale;
}
interface RowsLike {
    get(id: string): { performance: CellLike } | undefined;
}

// Honest Performance headline: ETS-weighted average of per-topic non-abstained
// Performance points. Falls back to a plain mean if the contributing topics
// carry no ETS weight (weights sum to 0). Abstains when no topic is timed.
export function buildPerformanceHeadline(
    leaves: Row[],
    rows: RowsLike,
): PerformanceHeadline {
    let wsum = 0;
    let acc = 0;
    let plain = 0;
    let timedTopics = 0;
    for (const leaf of leaves) {
        const cell = rows.get(leaf.id)?.performance;
        if (!cell || cell.abstained) {
            continue;
        }
        timedTopics += 1;
        plain += cell.point;
        wsum += leaf.weight;
        acc += leaf.weight * cell.point;
    }
    if (timedTopics === 0) {
        return { abstained: true, pct: 0, timedTopics: 0 };
    }
    const avg = wsum > 0 ? acc / wsum : plain / timedTopics;
    return {
        abstained: false,
        pct: Math.max(0, Math.min(100, avg * 100)),
        timedTopics,
    };
}

// Honest Readiness headline: the engine's exam-level 200–990 score, or the
// abstain reason + top unlock hint when it locks.
export function buildReadinessHeadline(
    overall: CellLike,
    abstainReason: string,
    unlocks: UnlockHint[],
): ReadinessHeadline {
    if (overall.abstained) {
        return {
            abstained: true,
            point: 0,
            lower: 0,
            upper: 0,
            percentile: 0,
            meterPct: 0,
            reason: abstainReason,
            unlockHuman: unlocks.length > 0 ? unlocks[0].human : "",
            nearCeiling: false,
        };
    }
    const meterPct = Math.max(
        0,
        Math.min(100, ((overall.point - GRE_MIN) / (GRE_MAX - GRE_MIN)) * 100),
    );
    return {
        abstained: false,
        point: overall.point,
        lower: overall.lower,
        upper: overall.upper,
        percentile: overall.percentile,
        meterPct,
        reason: "",
        unlockHuman: "",
        // Only real+high scores flag diminishing returns (abstained is handled
        // above and always returns false — never a plateau claim on empty state).
        nearCeiling: overall.point >= READINESS_CEILING,
    };
}

// Honest Calibration headline. The engine already abstains below its attempt
// threshold; this pass-through keeps the abstain honest (zeroing the numbers)
// and converts the ECE reliability gap to percentage points for the sub-hint.
export function buildCalibrationHeadline(
    cal: CalibrationData,
): CalibrationHeadline {
    if (cal.abstained) {
        return { abstained: true, brier: 0, gapPct: 0, attempts: cal.attempts };
    }
    return {
        abstained: false,
        brier: cal.brier,
        gapPct: Math.max(0, Math.min(100, cal.ece * 100)),
        attempts: cal.attempts,
    };
}
