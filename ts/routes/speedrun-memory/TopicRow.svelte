<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import type { Row, TopicScaffoldRow } from "./data";
    import RangeBand from "./RangeBand.svelte";

    export let row: Row;
    // scaffold: future PERFORMANCE/READINESS model output; always abstaining today.
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    export let scaffold: TopicScaffoldRow | undefined = undefined;
    // Derive cell text from scaffold when real models land (abstained=false).
    // For now every cell shows —.
    $: perfCell = scaffold?.performance.abstained !== false ? "—" : "?";
    $: readyCell = scaffold?.readiness.abstained !== false ? "—" : "?";
</script>

<tr class:abstained={row.abstained}>
    <td class="topic">
        {row.label}
        <span class="weight">({Math.round(row.weight * 100)}%)</span>
    </td>
    {#if row.abstained}
        <td class="recall">—</td>
        <td class="range" colspan="1">
            <span class="abstain-full">
                🔒 INSUFFICIENT DATA: review {row.unlockN} more to unlock
            </span>
            <span class="abstain-compact">🔒 {row.unlockN} more to unlock</span>
        </td>
        <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
        <td class="scaffold c-perf">{perfCell}</td>
        <td class="scaffold c-ready">{readyCell}</td>
    {:else}
        <td class="recall">{Math.round(row.avgRecall * 100)}%</td>
        <td class="range">
            <RangeBand lower={row.lower} upper={row.upper} point={row.avgRecall} />
        </td>
        <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
        <td class="scaffold c-perf">{perfCell}</td>
        <td class="scaffold c-ready">{readyCell}</td>
    {/if}
</tr>

<style>
    tr.abstained {
        opacity: 0.55;
    }
    .weight {
        color: var(--fg-subtle, #888);
        font-size: 0.85em;
    }
    .data {
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .scaffold {
        color: var(--fg-subtle, #888);
        font-variant-numeric: tabular-nums;
    }

    /* Mobile: ::before data labels for stacked cells (hidden at ≥768px) */
    .topic::before {
        content: "TOPIC ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .recall::before {
        content: "RECALL: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .range::before {
        content: "RANGE (95%): ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .data::before {
        content: "DATA: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    /* Two scaffold cells distinguished by added classes c-perf / c-ready */
    .c-perf::before {
        content: "PERFORMANCE: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .c-ready::before {
        content: "READINESS: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--fg-subtle, #888);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* Desktop restore: hide ::before labels at ≥768px */
    @media (min-width: 768px) {
        .topic::before,
        .recall::before,
        .range::before,
        .data::before,
        .c-perf::before,
        .c-ready::before {
            content: none;
        }
    }

    /* M0.8: compact abstain wording toggle */
    .abstain-compact {
        display: inline;
    }
    .abstain-full {
        display: none;
    }
    @media (min-width: 480px) {
        .abstain-compact {
            display: none;
        }
        .abstain-full {
            display: inline;
        }
    }
</style>
