<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import type { Row } from "./data";
    import RangeBand from "./RangeBand.svelte";

    export let row: Row;
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
    {:else}
        <td class="recall">{Math.round(row.avgRecall * 100)}%</td>
        <td class="range">
            <RangeBand lower={row.lower} upper={row.upper} point={row.avgRecall} />
        </td>
        <td class="data">{row.masteredCount}/{row.cardsWithData} cards</td>
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
</style>
