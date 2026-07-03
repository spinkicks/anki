// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import type { ExamProfile, Row } from "@speedrun/data";
import { describe, expect, test } from "vitest";

import {
    blastRadius,
    computeDepths,
    isCoveredLeaf,
    layoutNodes,
    masteryColor,
} from "./graph";

function row(id: string, partial: Partial<Row> = {}): Row {
    return {
        id,
        label: id,
        weight: 0.1,
        isContainer: false,
        root: id.split("::")[0],
        avgRecall: 0,
        lower: 0,
        upper: 1,
        masteredCount: 0,
        cardsWithData: 0,
        gradedReviews: 0,
        abstained: true,
        unlockN: 20,
        ...partial,
    };
}

const profile: ExamProfile = {
    exam_id: "gre_math",
    name: "GRE Math",
    topics: [
        { id: "calc", name: "Calculus", ets_weight: 0, prereqs: [] },
        { id: "calc::limits", name: "Limits", ets_weight: 0.1, prereqs: ["calc"] },
        { id: "calc::diff", name: "Differentiation", ets_weight: 0.14, prereqs: ["calc::limits"] },
        { id: "la", name: "Linear algebra", ets_weight: 0, prereqs: [] },
        { id: "la::matrices", name: "Matrices", ets_weight: 0.1, prereqs: ["la"] },
    ],
};

const rows: Row[] = [
    row("calc", { isContainer: true, weight: 0 }),
    row("calc::limits", { weight: 0.1 }),
    row("calc::diff", { weight: 0.14 }),
    row("la", { isContainer: true, weight: 0 }),
    row("la::matrices", { weight: 0.1 }),
];

describe("computeDepths", () => {
    test("longest prereq chain sets the column", () => {
        const d = computeDepths(profile.topics);
        expect(d.get("calc")).toBe(0);
        expect(d.get("calc::limits")).toBe(1);
        expect(d.get("calc::diff")).toBe(2);
        expect(d.get("la")).toBe(0);
        expect(d.get("la::matrices")).toBe(1);
    });
});

describe("layoutNodes", () => {
    test("keeps every row and places deeper topics further right", () => {
        const view = layoutNodes(rows, profile);
        expect(view.nodes).toHaveLength(5);
        const x = (id: string) => view.nodes.find((n) => n.id === id)!.x;
        expect(x("calc")).toBeLessThan(x("calc::limits"));
        expect(x("calc::limits")).toBeLessThan(x("calc::diff"));
    });
    test("builds one forward edge per valid prereq link", () => {
        const view = layoutNodes(rows, profile);
        expect(view.edges).toHaveLength(3);
        expect(view.edges).toContainEqual({ from: "calc", to: "calc::limits" });
        expect(view.edges).toContainEqual({ from: "calc::limits", to: "calc::diff" });
    });
});

describe("blastRadius", () => {
    const view = layoutNodes(rows, profile);
    test("a root caps everything downstream, transitively", () => {
        const b = blastRadius("calc", view.edges);
        expect([...b].sort()).toEqual(["calc::diff", "calc::limits"]);
    });
    test("a mid node caps only its descendants", () => {
        expect([...blastRadius("calc::limits", view.edges)]).toEqual(["calc::diff"]);
    });
    test("a leaf caps nothing", () => {
        expect(blastRadius("calc::diff", view.edges).size).toBe(0);
    });
    test("linear-algebra chain is independent of calculus", () => {
        expect([...blastRadius("la", view.edges)]).toEqual(["la::matrices"]);
    });
});

describe("isCoveredLeaf", () => {
    const view = layoutNodes(rows, profile);
    const byId = (id: string) => view.nodes.find((n) => n.id === id)!;
    test("a weighted (non-container) leaf is a covered leaf", () => {
        expect(isCoveredLeaf(byId("calc::limits"))).toBe(true);
        expect(isCoveredLeaf(byId("la::matrices"))).toBe(true);
    });
    test("a container/root is NOT a covered leaf", () => {
        expect(isCoveredLeaf(byId("calc"))).toBe(false);
        expect(isCoveredLeaf(byId("la"))).toBe(false);
    });
    test("null/undefined is not a covered leaf", () => {
        expect(isCoveredLeaf(null)).toBe(false);
        expect(isCoveredLeaf(undefined)).toBe(false);
    });
});

describe("masteryColor", () => {
    const view = layoutNodes(rows, profile);
    const node = (id: string, patch: Partial<Row> = {}) => {
        const r = { ...rows.find((x) => x.id === id)!, ...patch };
        return layoutNodes([r], { ...profile, topics: profile.topics.filter((t) => t.id === id) })
            .nodes[0];
    };
    test("containers and abstains are neutral grey (never a fake color)", () => {
        expect(masteryColor(view.nodes.find((n) => n.id === "calc")!)).toBe("#2b333d");
        expect(masteryColor(view.nodes.find((n) => n.id === "calc::limits")!)).toBe("#333b45");
    });
    test("strong recall is green, weak is brick", () => {
        expect(masteryColor(node("calc::limits", { abstained: false, avgRecall: 1 }))).toBe("#5aa96a");
        expect(masteryColor(node("calc::limits", { abstained: false, avgRecall: 0 }))).toBe("#b4573f");
    });
});
