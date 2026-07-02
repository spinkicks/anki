// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { type Row, ScoreScale } from "@speedrun/data";
import { expect, test } from "vitest";

import { buildPerformanceHeadline, buildReadinessHeadline } from "./data";

function leaf(id: string, weight: number): Row {
    return {
        id,
        label: id,
        weight,
        isContainer: false,
        root: id.split("::")[0],
        avgRecall: 0,
        lower: 0,
        upper: 1,
        masteredCount: 0,
        cardsWithData: 0,
        gradedReviews: 0,
        abstained: false,
        unlockN: 0,
    };
}

function unitCell(point: number, abstained = false) {
    return {
        abstained,
        point,
        lower: 0,
        upper: 1,
        percentile: 0,
        scale: ScoreScale.UNIT,
    };
}

test("performance headline abstains when no topic is timed", () => {
    const leaves = [leaf("calc", 0.5), leaf("alg", 0.5)];
    const rows = new Map([
        ["calc", { performance: unitCell(0, true) }],
        ["alg", { performance: unitCell(0, true) }],
    ]);
    const h = buildPerformanceHeadline(leaves, rows);
    expect(h.abstained).toBe(true);
    expect(h.pct).toBe(0);
    expect(h.timedTopics).toBe(0);
});

test("performance headline is the ETS-weighted average of real topics", () => {
    const leaves = [leaf("calc", 0.75), leaf("alg", 0.25)];
    const rows = new Map([
        ["calc", { performance: unitCell(0.8) }], // real
        ["alg", { performance: unitCell(0.4) }], // real
    ]);
    const h = buildPerformanceHeadline(leaves, rows);
    expect(h.abstained).toBe(false);
    expect(h.timedTopics).toBe(2);
    // (0.75*0.8 + 0.25*0.4) / (0.75+0.25) = 0.7 -> 70%
    expect(h.pct).toBeCloseTo(70);
});

test("performance headline ignores abstaining topics in the aggregate", () => {
    const leaves = [leaf("calc", 0.5), leaf("alg", 0.5)];
    const rows = new Map([
        ["calc", { performance: unitCell(0.9) }], // real
        ["alg", { performance: unitCell(0, true) }], // abstains -> excluded
    ]);
    const h = buildPerformanceHeadline(leaves, rows);
    expect(h.timedTopics).toBe(1);
    expect(h.pct).toBeCloseTo(90);
});

test("readiness headline maps the engine's 200–990 score + meter", () => {
    const overall = {
        abstained: false,
        point: 595, // midpoint of 200..990
        lower: 540,
        upper: 650,
        percentile: 61,
        scale: ScoreScale.GRE_200_990,
    };
    const h = buildReadinessHeadline(overall, "", []);
    expect(h.abstained).toBe(false);
    expect(h.point).toBe(595);
    expect(h.percentile).toBe(61);
    expect(h.meterPct).toBeCloseTo(50); // (595-200)/(990-200)*100
});

test("readiness headline abstains with the top unlock hint", () => {
    const overall = {
        abstained: true,
        point: 0,
        lower: 0,
        upper: 0,
        percentile: 0,
        scale: ScoreScale.GRE_200_990,
    };
    const h = buildReadinessHeadline(overall, "Readiness locked", [
        { kind: "mini_mocks", have: 0, need: 3, human: "Complete 3 more timed mini-mock(s)", topic: "" },
    ]);
    expect(h.abstained).toBe(true);
    expect(h.point).toBe(0);
    expect(h.unlockHuman).toBe("Complete 3 more timed mini-mock(s)");
    expect(h.reason).toBe("Readiness locked");
});
