// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import type { Row, ScaffoldCell, TopicScaffoldRow } from "@speedrun/data";
import { describe, expect, test } from "vitest";

import { gapItems } from "./gap";

function row(id: string, patch: Partial<Row> = {}): Row {
    return {
        id,
        label: id,
        weight: 0.1,
        isContainer: false,
        root: "calc",
        avgRecall: 0.9,
        lower: 0,
        upper: 1,
        masteredCount: 0,
        cardsWithData: 5,
        gradedReviews: 30,
        abstained: false,
        unlockN: 0,
        ...patch,
    };
}

function cell(patch: Partial<ScaffoldCell> = {}): ScaffoldCell {
    return {
        abstained: false,
        point: 0.6,
        lower: 0.4,
        upper: 0.8,
        percentile: 0,
        scale: 0,
        gapDelta: 0,
        ...patch,
    };
}

function scaf(perf: ScaffoldCell): TopicScaffoldRow {
    return { performance: perf, readiness: cell({ abstained: true }), gapDelta: 0 };
}

describe("gapItems", () => {
    test("only includes topics where recall AND performance are both real", () => {
        const rows = [
            row("a", { avgRecall: 0.9 }),
            row("b", { abstained: true }), // recall abstains -> excluded
            row("c"),
            row("grp", { isContainer: true }), // container -> excluded
        ];
        const scaffold = new Map<string, TopicScaffoldRow>([
            ["a", scaf(cell({ point: 0.6 }))],
            ["b", scaf(cell({ point: 0.6 }))],
            ["c", scaf(cell({ abstained: true }))], // perf abstains -> excluded
        ]);
        const items = gapItems(rows, scaffold);
        expect(items.map((i) => i.id)).toEqual(["a"]);
        expect(items[0].gap).toBeCloseTo(0.6 - 0.9, 6);
    });

    test("sorts by largest absolute gap first", () => {
        const rows = [
            row("small", { avgRecall: 0.55 }),
            row("big", { avgRecall: 0.95 }),
        ];
        const scaffold = new Map<string, TopicScaffoldRow>([
            ["small", scaf(cell({ point: 0.6 }))], // |+0.05|
            ["big", scaf(cell({ point: 0.3 }))], // |-0.65|
        ]);
        expect(gapItems(rows, scaffold).map((i) => i.id)).toEqual(["big", "small"]);
    });
});
