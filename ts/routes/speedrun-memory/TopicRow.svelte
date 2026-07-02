<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import type { Row, TopicScaffoldRow } from "./data";
    import RangeBand from "./RangeBand.svelte";

    export let row: Row;
    // scaffold: PERFORMANCE / READINESS model output. Each cell abstains until
    // the engine has real data (abstained=false) — we never invent a number.
    export let scaffold: TopicScaffoldRow | undefined = undefined;

    $: perf = scaffold?.performance;
    $: ready = scaffold?.readiness;
    // A cell renders a real band only when the engine marks it non-abstained.
    $: perfReal = perf?.abstained === false;
    $: readyReal = ready?.abstained === false;
    // Tooltips surface the percentile when present (0 while abstaining).
    $: perfTitle = perfReal && perf ? `Percentile ${Math.round(perf.percentile)}` : "";
    $: readyTitle =
        readyReal && ready ? `Percentile ${Math.round(ready.percentile)}` : "";

    // §7d gap meter: declarative recall − problem accuracy. Only meaningful when
    // Performance is real (both sides present); otherwise honest "—".
    $: gap = scaffold?.gapDelta ?? 0;
    $: gapText = perfReal ? `${gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(2)}` : "—";
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
    {:else}
        <td class="recall">{Math.round(row.avgRecall * 100)}%</td>
        <td class="range">
            <RangeBand lower={row.lower} upper={row.upper} point={row.avgRecall} />
        </td>
    {/if}
    <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
    <td class="scaffold c-perf" title={perfTitle}>
        {#if perfReal && perf}
            <RangeBand
                lower={perf.lower}
                upper={perf.upper}
                point={perf.point}
                scale={perf.scale}
            />
        {:else}
            —
        {/if}
    </td>
    <td class="scaffold c-ready" title={readyTitle}>
        {#if readyReal && ready}
            <RangeBand
                lower={ready.lower}
                upper={ready.upper}
                point={ready.point}
                scale={ready.scale}
            />
        {:else}
            —
        {/if}
    </td>
    <td class="scaffold c-gap">{gapText}</td>
</tr>

<style>
    tr.abstained {
        opacity: 0.55;
    }
    .weight {
        color: var(--muted);
        font-size: 0.85em;
    }
    .data {
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .scaffold {
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    /* Mobile: ::before data labels for stacked cells (hidden at ≥768px) */
    .topic::before {
        content: "TOPIC ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .recall::before {
        content: "RECALL: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .range::before {
        content: "RANGE (95%): ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .data::before {
        content: "DATA: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    /* Scaffold cells distinguished by added classes c-perf / c-ready / c-gap */
    .c-perf::before {
        content: "PERFORMANCE: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .c-ready::before {
        content: "READINESS: ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .c-gap::before {
        content: "GAP (Δ): ";
        font-size: 0.75em;
        font-weight: 600;
        color: var(--muted);
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
        .c-ready::before,
        .c-gap::before {
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
