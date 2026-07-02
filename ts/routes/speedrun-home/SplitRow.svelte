<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

THE SIGNATURE ELEMENT — the split row. A timed leaf reads like a speedrun split:
    topic  recall%  |—[low–high]—|  range%  ✓
with an inline 95% confidence error-bracket band (bracket = interval, amber tick
= point estimate). An abstained leaf dims and shows the unlock message instead.
-->
<script lang="ts">
    import type { Row } from "@speedrun/data";

    export let row: Row;

    // Band geometry in percent. The bracket spans lower..upper; `right` is the
    // inset from 100 (matches the mockup's `right:` inline style). The amber
    // point tick sits at avgRecall.
    $: pct = (v: number) => Math.max(0, Math.min(100, v * 100));
    $: leftPct = pct(row.lower);
    $: rightInset = 100 - pct(row.upper);
    $: pointPct = pct(row.avgRecall);
    $: recall = Math.round(row.avgRecall * 100);
    $: rangeLo = Math.round(row.lower * 100);
    $: rangeHi = Math.round(row.upper * 100);
</script>

{#if row.abstained}
    <tr class="row abstain">
        <td class="c-topic">{row.label}</td>
        <td class="c-recall">—</td>
        <td class="c-band" colspan="2">
            <span class="locked">
                <span class="abstain-full">
                    NOT TIMED — review <b>{row.unlockN} more</b>
                     to unlock a split
                </span>
                <span class="abstain-compact">
                    🔒 <b>{row.unlockN} more</b>
                     to unlock
                </span>
            </span>
        </td>
        <td class="c-flag">▮</td>
    </tr>
{:else}
    <tr class="row">
        <td class="c-topic">{row.label}</td>
        <td class="c-recall">{recall}%</td>
        <td class="c-band">
            <div class="band">
                <span class="cap">0</span>
                <div class="track">
                    <div class="axis"></div>
                    <div
                        class="br"
                        style={`left:${leftPct}%;right:${rightInset}%`}
                    ></div>
                    <div class="pt" style={`left:${pointPct}%`}></div>
                </div>
                <span class="cap">100</span>
            </div>
        </td>
        <td class="c-range">{rangeLo}–{rangeHi}%</td>
        <td class="c-flag">✓</td>
    </tr>
{/if}

<style>
    /* Mobile-first base: stacked card layout */
    tr.row {
        display: block;
        min-height: 44px;
    }
    tr.row td {
        display: block;
        width: 100%;
        padding: 6px 16px;
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        font-size: 13px;
        border: none;
    }

    /* Mobile: topic on its own full-width line */
    .c-topic {
        color: var(--fg);
        letter-spacing: 0.02em;
    }

    /* Mobile: recall + range side-by-side (~48% each) */
    .c-recall {
        color: var(--fg);
        display: inline-block;
        width: 48%;
        text-align: left;
    }
    .c-range {
        color: var(--muted);
        display: inline-block;
        width: 48%;
        text-align: right;
    }

    /* Mobile: flag centered on its own line */
    .c-flag {
        text-align: center;
        color: var(--pace);
    }

    /* Desktop restore: table row layout with pixel widths */
    @media (min-width: 768px) {
        tr.row {
            display: table-row;
            min-height: unset;
        }
        tr.row td {
            display: table-cell;
            width: auto;
            padding: 7px 28px;
        }
        .c-topic {
            width: 200px;
        }
        .c-recall {
            display: table-cell;
            width: 60px;
            text-align: right;
        }
        .c-band {
            width: 300px;
        }
        .c-range {
            display: table-cell;
            width: 92px;
            text-align: right;
        }
        .c-flag {
            width: 40px;
        }
    }

    /* abstained rows dim */
    tr.abstain td {
        color: var(--muted);
    }
    tr.abstain .c-topic {
        color: var(--muted);
    }
    .locked {
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        font-size: 12px;
        color: var(--muted);
        letter-spacing: 0.04em;
    }
    .locked b {
        color: var(--pace);
        font-weight: 500;
    }

    /* M0.8: compact abstain copy — narrow screens show compact, wide show full */
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

    /* the signature: inline error-bracket band */
    .band {
        display: flex;
        align-items: center;
        gap: 0;
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        color: var(--muted);
    }
    .band .track {
        position: relative;
        height: 14px;
        flex: 1;
        margin: 0 6px;
    }
    .band .axis {
        position: absolute;
        top: 50%;
        left: 0;
        right: 0;
        height: 1px;
        background: var(--line);
    }
    .band .br {
        position: absolute;
        top: 2px;
        bottom: 2px;
        border-left: 2px solid var(--fg);
        border-right: 2px solid var(--fg);
    }
    .band .br::before {
        content: "";
        position: absolute;
        top: 50%;
        left: 0;
        right: 0;
        height: 3px;
        transform: translateY(-50%);
        background: var(--fg);
        opacity: 0.28;
    }
    .band .pt {
        position: absolute;
        top: -1px;
        width: 2px;
        height: 16px;
        background: var(--pace);
    }
    .band .cap {
        color: var(--muted);
        font-size: 12px;
    }
</style>
