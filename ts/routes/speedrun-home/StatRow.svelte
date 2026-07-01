<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    export let coverage: { covered: number; total: number; percent: number };
    // memoryVerified.timed = non-abstained leaves; .total = leaves with data.
    export let memoryVerified: { timed: number; total: number };

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
        <!-- Readiness is always-abstaining scaffolding today (real model later).
             Shown calmly muted with an empty amber (pace) meter. -->
        <div class="label">Readiness · pace</div>
        <div class="val muted">
            — <small>abstains</small>
        </div>
        <div class="meter pace"><i style="width:0%"></i></div>
    </div>
</div>

<style>
    .stats {
        display: flex;
        border-bottom: 1px solid var(--line);
    }
    .stat {
        flex: 1;
        padding: 16px 28px;
        border-right: 1px solid var(--line);
    }
    .stat:last-child {
        border-right: none;
    }
    .label {
        font-family: var(--mono);
        font-size: 10px;
        letter-spacing: 0.24em;
        color: var(--muted);
        text-transform: uppercase;
    }
    .val {
        font-family: var(--mono);
        font-size: 26px;
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
