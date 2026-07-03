<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Memory -> Performance gap. A slope chart: for each topic where both signals are
real, a line connects flashcard RECALL (left) to timed-problem PERFORMANCE
(right). A downhill line = "you remember it but can't use it yet" — the thesis
made visible. Abstaining topics are omitted, never faked.
-->
<script lang="ts">
    import type { Row, TopicScaffoldRow } from "@speedrun/data";

    import { gapItems } from "./gap";

    export let rows: Row[] = [];
    export let scaffold: Map<string, TopicScaffoldRow> = new Map();

    const H = 150;
    const TOP = 14;
    const BOT = 18;

    $: items = gapItems(rows, scaffold);
    $: y = (v: number) => TOP + (1 - Math.max(0, Math.min(1, v))) * (H - TOP - BOT);
</script>

<section class="gap">
    <h3>Memory → Performance gap <span class="sub">— recall vs. timed problem accuracy</span></h3>

    {#if items.length === 0}
        <p class="muted">
            No gap to show yet — this needs both a recall estimate and timed-problem
            accuracy on the same topic. Run mini-mocks on topics you've studied to reveal it.
        </p>
    {:else}
        <div class="rows">
            {#each items as it (it.id)}
                <div class="grow">
                    <span class="lab">{it.label}</span>
                    <svg viewBox={`0 0 200 ${H}`} class="slope" preserveAspectRatio="none"
                        role="img" aria-label={`${it.label}: recall ${Math.round(
                            it.recall * 100,
                        )} percent, performance ${Math.round(it.performance * 100)} percent`}>
                        <line x1="30" y1={TOP} x2="30" y2={H - BOT} class="axis" />
                        <line x1="170" y1={TOP} x2="170" y2={H - BOT} class="axis" />
                        <line
                            x1="30"
                            y1={y(it.recall)}
                            x2="170"
                            y2={y(it.performance)}
                            class:down={it.gap < -0.05}
                            class:up={it.gap > 0.05}
                            class="link"
                        />
                        <circle cx="30" cy={y(it.recall)} r="4" class="dot recall" />
                        <circle cx="170" cy={y(it.performance)} r="4" class="dot perf" />
                    </svg>
                    <span class="delta" class:neg={it.gap < 0}>
                        {it.gap >= 0 ? "+" : ""}{Math.round(it.gap * 100)}
                    </span>
                </div>
            {/each}
        </div>
        <div class="axes-legend">
            <span>RECALL</span>
            <span class="hint">↓ line = remembered but not yet usable</span>
            <span>PERFORMANCE</span>
        </div>
    {/if}
</section>

<style>
    .gap {
        margin-top: 20px;
        background: var(--panel, #12161c);
        border: 1px solid var(--line, #232a33);
        border-radius: 8px;
        padding: 14px 16px;
    }
    h3 {
        margin: 0 0 10px;
        font-size: 15px;
        font-weight: 800;
    }
    .sub {
        color: var(--muted, #7c8794);
        font-weight: 500;
        font-size: 13px;
    }
    .muted {
        color: var(--muted, #7c8794);
        font-size: 13px;
        line-height: 1.5;
        margin: 0;
    }
    .rows {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .grow {
        display: grid;
        grid-template-columns: 1fr 120px 40px;
        align-items: center;
        gap: 10px;
    }
    .lab {
        font-size: 13px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .slope {
        width: 120px;
        height: 44px;
    }
    .axis {
        stroke: var(--line, #232a33);
        stroke-width: 1;
    }
    .link {
        stroke: var(--muted, #7c8794);
        stroke-width: 2;
    }
    .link.down {
        stroke: #b4573f;
    }
    .link.up {
        stroke: #5aa96a;
    }
    .dot.recall {
        fill: var(--pace, #f4f7fa);
    }
    .dot.perf {
        fill: #8aa0b4;
    }
    .delta {
        font-variant-numeric: tabular-nums;
        font-weight: 800;
        font-size: 14px;
        text-align: right;
        color: #5aa96a;
    }
    .delta.neg {
        color: #b4573f;
    }
    .axes-legend {
        display: flex;
        justify-content: space-between;
        margin-top: 8px;
        font-size: 11px;
        letter-spacing: 0.04em;
        color: var(--muted, #7c8794);
    }
    .axes-legend .hint {
        font-style: italic;
    }
</style>
