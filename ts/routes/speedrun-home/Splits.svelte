<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import type { Row } from "@speedrun/data";

    import type { Segment } from "./data";
    import SplitRow from "./SplitRow.svelte";

    export let segments: Segment[];

    // Default sort = by ETS weight (segment order stays fixed; leaves keep their
    // profile order which is weight-descending). Toggle = weakest-timed-first:
    // ascending avgRecall among non-abstained leaves, with abstained rows pushed
    // to the bottom of each segment. Sorting only reorders leaves WITHIN a
    // segment; segment order never changes.
    let weakestFirst = false;

    function sortLeaves(rows: Row[]): Row[] {
        if (!weakestFirst) {
            return rows;
        }
        // Abstained rows sort as recall 2 (> any real 0..1 recall) => bottom.
        return [...rows].sort(
            (a, b) => (a.abstained ? 2 : a.avgRecall) - (b.abstained ? 2 : b.avgRecall),
        );
    }

    $: view = segments.map((s) => ({ ...s, rows: sortLeaves(s.rows) }));
</script>

<div class="splits-hd">
    <h2>Splits</h2>
    <button
        class="sort"
        on:click={() => (weakestFirst = !weakestFirst)}
        aria-pressed={weakestFirst}
    >
        SORT ▾ {weakestFirst ? "WEAKEST TIMED" : "WEIGHT"}
    </button>
</div>

<table>
    <tbody>
        {#each view as seg (seg.num)}
            <tr class="seg">
                <td colspan="5">
                    <span class="num">{seg.num}</span>
                    &nbsp;
                    <span class="name">{seg.name}</span>
                    <span class="wt">ETS WEIGHT {seg.weightPct}%</span>
                </td>
            </tr>
            {#each seg.rows as row (row.id)}
                <SplitRow {row} />
            {/each}
        {/each}
    </tbody>
</table>

<style>
    .splits-hd {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        /* Mobile-first base: wrap on narrow screens */
        flex-wrap: wrap;
        gap: 8px;
        padding: 16px;
    }
    /* Desktop restore: original padding */
    @media (min-width: 768px) {
        .splits-hd {
            flex-wrap: nowrap;
            gap: 0;
            padding: 20px 28px 10px;
        }
    }
    .splits-hd h2 {
        font-family: var(--disp);
        font-size: 12px;
        letter-spacing: 0.28em;
        color: var(--fg);
        text-transform: uppercase;
        font-weight: 600;
    }
    .sort {
        font-family: var(--disp);
        font-size: 11px;
        letter-spacing: 0.12em;
        color: var(--muted);
        text-transform: uppercase;
        background: none;
        border: none;
        cursor: pointer;
        /* Mobile-first: ≥44px touch target */
        padding: 10px 12px;
        margin: -10px -12px;
        min-height: 44px;
    }
    .sort:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
    table {
        width: 100%;
        border-collapse: collapse;
    }
    .seg td {
        padding: 16px 28px 6px;
        border-top: 1px solid var(--line);
    }
    .seg .num {
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        color: var(--pace);
        font-size: 12px;
        letter-spacing: 0.1em;
    }
    .seg .name {
        font-family: var(--disp);
        font-weight: 700;
        font-size: 13px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }
    .seg .wt {
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        color: var(--muted);
        font-size: 11px;
        float: right;
        letter-spacing: 0.08em;
    }
</style>
