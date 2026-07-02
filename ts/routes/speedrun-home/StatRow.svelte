<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import type { PerformanceHeadline, ReadinessHeadline } from "./data";

    export let coverage: { covered: number; total: number; percent: number };
    // memoryVerified.timed = non-abstained leaves; .total = leaves with data.
    export let memoryVerified: { timed: number; total: number };
    // Honest headline stats from the engine (abstain until real data exists).
    export let performance: PerformanceHeadline;
    export let readiness: ReadinessHeadline;

    // Meter widths clamp to [0,100]. Memory meter = timed / total; guard /0 so a
    // fresh deck (no data yet) reads a calm empty meter rather than NaN.
    $: coveragePct = Math.max(0, Math.min(100, coverage.percent));
    $: memoryPct =
        memoryVerified.total > 0
            ? Math.max(
                  0,
                  Math.min(100, (memoryVerified.timed / memoryVerified.total) * 100),
              )
            : 0;
</script>

<div class="stats">
    <div class="stat">
        <div class="label">Coverage</div>
        <div class="val">
            {coverage.covered}
            <small>/{coverage.total} topics</small>
        </div>
        <div class="meter"><i style={`width:${coveragePct}%`}></i></div>
    </div>
    <div class="stat">
        <div class="label">Memory · verified</div>
        <div class="val">
            {memoryVerified.timed}
            <small>/{memoryVerified.total} timed</small>
        </div>
        <div class="meter"><i style={`width:${memoryPct}%`}></i></div>
    </div>
    <div class="stat">
        <!-- Performance = demonstrated problem accuracy (ETS-weighted), only once
             a topic has real timed data; abstains calmly otherwise. -->
        <div class="label">Performance</div>
        {#if performance.abstained}
            <div class="val muted">
                — <small>abstains</small>
            </div>
            <div class="meter"><i style="width:0%"></i></div>
        {:else}
            <div class="val">
                {Math.round(performance.pct)}%
                <small>/{performance.timedTopics} timed</small>
            </div>
            <div class="meter">
                <i style={`width:${Math.round(performance.pct)}%`}></i>
            </div>
        {/if}
    </div>
    <div class="stat">
        <!-- Readiness = exam-level 200–990. Abstains (with an unlock hint) until
             the engine's give-up rule is met; never a guessed number. -->
        <div class="label">Readiness · pace</div>
        {#if readiness.abstained}
            <div class="val muted">
                — <small>abstains</small>
            </div>
            <div class="meter pace"><i style="width:0%"></i></div>
            {#if readiness.unlockHuman}
                <div class="hint">{readiness.unlockHuman}</div>
            {:else if readiness.reason}
                <div class="hint">{readiness.reason}</div>
            {/if}
        {:else}
            <div class="val">
                {Math.round(readiness.point)}
                <small>·{Math.round(readiness.percentile)}%ile</small>
            </div>
            <div class="meter pace">
                <i style={`width:${Math.round(readiness.meterPct)}%`}></i>
            </div>
            <div class="hint">
                {Math.round(readiness.lower)}–{Math.round(readiness.upper)} (95%)
            </div>
        {/if}
    </div>
</div>

<style>
    /* Mobile-first base: stacked column layout */
    .stats {
        display: flex;
        border-bottom: 1px solid var(--line);
        flex-direction: column;
    }
    .stat {
        flex: 1;
        padding: 12px 16px;
        border-right: none;
        border-bottom: 1px solid var(--line);
    }
    .stat:last-child {
        border-bottom: none;
    }
    /* Desktop restore: horizontal row */
    @media (min-width: 768px) {
        .stats {
            flex-direction: row;
        }
        .stat {
            padding: 16px 28px;
            border-right: 1px solid var(--line);
            border-bottom: none;
        }
        .stat:last-child {
            border-right: none;
        }
    }
    .label {
        font-family: var(--disp);
        font-size: 10px;
        letter-spacing: 0.24em;
        color: var(--muted);
        text-transform: uppercase;
    }
    .val {
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        font-size: clamp(20px, 6vw, 26px);
        font-weight: 500;
        margin-top: 8px;
        letter-spacing: 0.02em;
    }
    .val.muted {
        color: var(--muted);
    }
    .val small {
        color: var(--muted);
        font-size: 14px;
    }
    .hint {
        margin-top: 8px;
        font-family: var(--mono);
        font-size: 10px;
        letter-spacing: 0.08em;
        color: var(--muted);
        text-transform: uppercase;
    }
    .meter {
        height: 6px;
        background: #0a0d11;
        border: 1px solid var(--line);
        margin-top: 10px;
        position: relative;
    }
    .meter i {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        background: var(--fg);
    }
    .meter.pace i {
        background: var(--pace);
    }
</style>
