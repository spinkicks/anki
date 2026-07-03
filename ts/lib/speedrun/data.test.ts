// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { ScoreScale } from "@generated/anki/speedrun_pb";
import { expect, test } from "vitest";

import {
    type CalibrationResponseLike,
    mapCalibrationResponse,
    mapScaffoldResponse,
    type ScaffoldResponseLike,
} from "./data";

// A real (non-abstained) UNIT Performance cell + an abstaining scaled Readiness
// (this mirrors what the engine emits per-topic: Readiness abstains per-topic,
// the real headline lives at response-level overall_readiness).
const REAL_RESP: ScaffoldResponseLike = {
    scaffolding: false,
    abstainReason: "",
    topics: [
        {
            topic: "calc::integration",
            performance: {
                abstained: false,
                point: 0.72,
                lower: 0.6,
                upper: 0.84,
                percentile: 0,
                scale: ScoreScale.UNIT,
                lastUpdated: 100n,
            },
            readiness: {
                abstained: true,
                point: 0,
                lower: 0,
                upper: 0,
                percentile: 0,
                scale: ScoreScale.GRE_200_990,
                lastUpdated: 0n,
            },
            gapDelta: 0.12,
        },
    ],
    overallReadiness: {
        abstained: false,
        point: 620,
        lower: 540,
        upper: 700,
        percentile: 61,
        scale: ScoreScale.GRE_200_990,
        lastUpdated: 100n,
    },
    unlockRequirements: [],
};

test("maps every ScoreScaffold field through the boundary", () => {
    const summary = mapScaffoldResponse(REAL_RESP);
    const cell = summary.rows.get("calc::integration");
    expect(cell).toBeDefined();
    const perf = cell!.performance;
    expect(perf.abstained).toBe(false);
    expect(perf.point).toBeCloseTo(0.72);
    expect(perf.lower).toBeCloseTo(0.6);
    expect(perf.upper).toBeCloseTo(0.84);
    expect(perf.percentile).toBe(0);
    expect(perf.scale).toBe(ScoreScale.UNIT);
    // gap-delta is carried on the row (topic-level, not per-cell in the proto).
    expect(cell!.gapDelta).toBeCloseTo(0.12);
});

test("carries per-topic readiness scale (GRE_200_990) untouched", () => {
    const summary = mapScaffoldResponse(REAL_RESP);
    const cell = summary.rows.get("calc::integration")!;
    expect(cell.readiness.abstained).toBe(true);
    expect(cell.readiness.scale).toBe(ScoreScale.GRE_200_990);
});

test("surfaces response-level overall readiness + unlock hints", () => {
    const summary = mapScaffoldResponse(REAL_RESP);
    expect(summary.overallReadiness.abstained).toBe(false);
    expect(summary.overallReadiness.point).toBe(620);
    expect(summary.overallReadiness.lower).toBe(540);
    expect(summary.overallReadiness.upper).toBe(700);
    expect(summary.overallReadiness.percentile).toBe(61);
    expect(summary.overallReadiness.scale).toBe(ScoreScale.GRE_200_990);
    expect(summary.abstainReason).toBe("");
    expect(summary.unlockRequirements).toHaveLength(0);
});

test("defaults to abstain (honest) when fields are absent", () => {
    // A response with a topic that has no performance/readiness sub-messages and
    // no overall_readiness — the boundary must NOT fabricate a number.
    const resp: ScaffoldResponseLike = {
        topics: [{ topic: "topology" }],
    };
    const summary = mapScaffoldResponse(resp);
    const cell = summary.rows.get("topology")!;
    expect(cell.performance.abstained).toBe(true);
    expect(cell.performance.point).toBe(0);
    expect(cell.readiness.abstained).toBe(true);
    expect(cell.gapDelta).toBe(0);
    // No overall_readiness => abstaining scaled cell, still on the GRE scale.
    expect(summary.overallReadiness.abstained).toBe(true);
    expect(summary.overallReadiness.scale).toBe(ScoreScale.GRE_200_990);
    expect(summary.unlockRequirements).toHaveLength(0);
});

test("carries unlock requirements + abstain reason when readiness locks", () => {
    const resp: ScaffoldResponseLike = {
        scaffolding: true,
        abstainReason: "Readiness locked until the give-up rule is met",
        topics: [],
        overallReadiness: { abstained: true, scale: ScoreScale.GRE_200_990 },
        unlockRequirements: [
            {
                kind: "mini_mocks",
                have: 0,
                need: 3,
                human: "Complete 3 more timed mini-mock(s)",
                topic: "",
            },
        ],
    };
    const summary = mapScaffoldResponse(resp);
    expect(summary.abstainReason).toBe("Readiness locked until the give-up rule is met");
    expect(summary.unlockRequirements[0].human).toBe("Complete 3 more timed mini-mock(s)");
    expect(summary.unlockRequirements[0].kind).toBe("mini_mocks");
});

test("maps a scored CalibrationResponse through the boundary", () => {
    const resp: CalibrationResponseLike = {
        abstained: false,
        brier: 0.09,
        ece: 0.0,
        attempts: 20,
        backendVersion: "test",
        bins: [{ confidence: 0.9, accuracy: 0.9, n: 20 }],
    };
    const h = mapCalibrationResponse(resp);
    expect(h.abstained).toBe(false);
    expect(h.brier).toBeCloseTo(0.09);
    expect(h.ece).toBeCloseTo(0.0);
    expect(h.attempts).toBe(20);
    expect(h.bins).toHaveLength(1);
    expect(h.bins[0].confidence).toBeCloseTo(0.9);
    expect(h.bins[0].accuracy).toBeCloseTo(0.9);
    expect(h.bins[0].n).toBe(20);
});

test("calibration defaults to abstain (honest) when fields are absent", () => {
    // An empty/partial response must NOT fabricate a Brier/ECE number.
    const h = mapCalibrationResponse({});
    expect(h.abstained).toBe(true);
    expect(h.brier).toBe(0);
    expect(h.ece).toBe(0);
    expect(h.attempts).toBe(0);
    expect(h.bins).toHaveLength(0);
});
