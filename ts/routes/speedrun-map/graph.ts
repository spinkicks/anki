// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pure graph/layout logic for "The Map". No RPC/runtime imports (types only),
// so it is unit-testable without building the generated protobufs.

import type { ExamProfile, Row } from "@speedrun/data";

export interface MapNode {
    id: string;
    name: string;
    weight: number;
    isContainer: boolean;
    root: string;
    abstained: boolean;
    avgRecall: number;
    cardsWithData: number;
    gradedReviews: number;
    unlockN: number;
    depth: number; // longest prereq chain to a root (0 = foundational)
    x: number;
    y: number;
}

/** Forward edge: a prerequisite -> the topic that depends on it. */
export interface MapEdge {
    from: string;
    to: string;
}

export interface MapView {
    nodes: MapNode[];
    edges: MapEdge[];
    width: number;
    height: number;
}

const COL_W = 210;
const ROW_H = 78;
const MARGIN_X = 90;
const MARGIN_Y = 54;

/** Longest-path depth of every topic over the prereq DAG (memoised, cycle-safe). */
export function computeDepths(
    topics: { id: string; prereqs: string[] }[],
): Map<string, number> {
    const byId = new Map(topics.map((t) => [t.id, t]));
    const depth = new Map<string, number>();
    const visiting = new Set<string>();
    const walk = (id: string): number => {
        const cached = depth.get(id);
        if (cached !== undefined) return cached;
        const t = byId.get(id);
        if (!t || t.prereqs.length === 0 || visiting.has(id)) {
            depth.set(id, 0);
            return 0;
        }
        visiting.add(id);
        let best = 0;
        for (const p of t.prereqs) {
            if (byId.has(p)) best = Math.max(best, 1 + walk(p));
        }
        visiting.delete(id);
        depth.set(id, best);
        return best;
    };
    for (const t of topics) walk(t.id);
    return depth;
}

/** Deterministic layered layout: column = depth, rows spread + centered per column. */
export function layoutNodes(rows: Row[], profile: ExamProfile): MapView {
    const depths = computeDepths(profile.topics);
    const byDepth = new Map<number, Row[]>();
    for (const r of rows) {
        const d = depths.get(r.id) ?? 0;
        const list = byDepth.get(d) ?? [];
        list.push(r);
        byDepth.set(d, list);
    }
    const maxDepth = Math.max(0, ...[...byDepth.keys()]);
    let maxCol = 1;
    for (const list of byDepth.values()) maxCol = Math.max(maxCol, list.length);

    const nodes: MapNode[] = [];
    for (let d = 0; d <= maxDepth; d++) {
        const col = (byDepth.get(d) ?? []).slice().sort((a, b) =>
            a.root === b.root ? b.weight - a.weight : a.root.localeCompare(b.root)
        );
        const offset = (maxCol - col.length) / 2; // center shorter columns
        col.forEach((r, i) => {
            nodes.push({
                id: r.id,
                name: r.label,
                weight: r.weight,
                isContainer: r.isContainer,
                root: r.root,
                abstained: r.abstained,
                avgRecall: r.avgRecall,
                cardsWithData: r.cardsWithData,
                gradedReviews: r.gradedReviews,
                unlockN: r.unlockN,
                depth: d,
                x: MARGIN_X + d * COL_W,
                y: MARGIN_Y + (i + offset) * ROW_H,
            });
        });
    }
    const edges: MapEdge[] = [];
    const ids = new Set(rows.map((r) => r.id));
    for (const t of profile.topics) {
        for (const p of t.prereqs) {
            if (ids.has(p) && ids.has(t.id)) edges.push({ from: p, to: t.id });
        }
    }
    return {
        nodes,
        edges,
        width: MARGIN_X * 2 + maxDepth * COL_W,
        height: MARGIN_Y * 2 + (maxCol - 1) * ROW_H,
    };
}

/**
 * Blast radius = every topic that (transitively) DEPENDS ON the selected one,
 * i.e. downstream topics its weakness caps. Follows forward edges (prereq -> dependent).
 */
export function blastRadius(rootId: string, edges: MapEdge[]): Set<string> {
    const forward = new Map<string, string[]>();
    for (const e of edges) {
        const list = forward.get(e.from) ?? [];
        list.push(e.to);
        forward.set(e.from, list);
    }
    const out = new Set<string>();
    const stack = [rootId];
    while (stack.length) {
        const cur = stack.pop() as string;
        for (const next of forward.get(cur) ?? []) {
            if (!out.has(next)) {
                out.add(next);
                stack.push(next);
            }
        }
    }
    return out;
}

/** Muted status color by recall; abstaining/container nodes are neutral grey. */
export function masteryColor(node: MapNode): string {
    if (node.isContainer) return "#2b333d";
    if (node.abstained) return "#333b45";
    const r = Math.max(0, Math.min(1, node.avgRecall));
    // weak (brick) -> mid (muted gold) -> strong (green), low saturation for a dark UI.
    if (r < 0.5) return lerpHex("#b4573f", "#c9a24a", r / 0.5);
    return lerpHex("#c9a24a", "#5aa96a", (r - 0.5) / 0.5);
}

function lerpHex(a: string, b: string, t: number): string {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
    const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    const clamp = Math.max(0, Math.min(1, t));
    const p = pa.map((v, i) => Math.round(v + (pb[i] - v) * clamp));
    return `#${p.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
