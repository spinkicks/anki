// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Pure logic for the Memory->Performance gap visual. Only topics where BOTH
// recall AND performance are real (non-abstained) qualify — never fabricate a
// gap from abstaining data (mirrors the P0 #3 honesty fix).

import type { Row, TopicScaffoldRow } from "@speedrun/data";

export interface GapItem {
    id: string;
    label: string;
    recall: number; // 0..1
    performance: number; // 0..1
    gap: number; // performance - recall (negative = "remember it but can't use it yet")
}

export function gapItems(
    rows: Row[],
    scaffold: Map<string, TopicScaffoldRow>,
): GapItem[] {
    const out: GapItem[] = [];
    for (const r of rows) {
        if (r.isContainer || r.abstained) continue;
        const s = scaffold.get(r.id);
        if (!s || s.performance.abstained) continue;
        out.push({
            id: r.id,
            label: r.label,
            recall: r.avgRecall,
            performance: s.performance.point,
            gap: s.performance.point - r.avgRecall,
        });
    }
    // Largest absolute gap first — the most diagnostic rows lead.
    return out.sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
}
