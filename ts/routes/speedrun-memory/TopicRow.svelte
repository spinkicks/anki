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
            🔒 INSUFFICIENT DATA: review {row.unlockN} more to unlock
        </td>
        <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
        <td class="scaffold">{perfCell}</td>
        <td class="scaffold">{readyCell}</td>
    {:else}
        <td class="recall">{Math.round(row.avgRecall * 100)}%</td>
        <td class="range">
            <RangeBand lower={row.lower} upper={row.upper} point={row.avgRecall} />
        </td>
        <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
        <td class="scaffold">{perfCell}</td>
        <td class="scaffold">{readyCell}</td>
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
</style>
