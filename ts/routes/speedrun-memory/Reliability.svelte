<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Calibration reliability diagram — the "weaponized honesty" showpiece. Plots the
user's stated confidence (self-bet) vs. their actual accuracy. Points on the
diagonal = well-calibrated; below = overconfident. Abstains below the LS1
data threshold rather than drawing a chart from too little data.
-->
<script lang="ts">
    import { onMount } from "svelte";
    import { type CalibrationHeadline, type ExamProfile, loadCalibration } from "@speedrun/data";

    import { plotBins } from "./reliability";

    export let profile: ExamProfile;

    const SIZE = 240;
    const PAD = 28;

    let cal: CalibrationHeadline | null = null;
    let failed = false;

    onMount(async () => {
        try {
            cal = await loadCalibration(profile);
        } catch {
            failed = true;
        }
    });

    $: points = cal ? plotBins(cal.bins, { size: SIZE, pad: PAD }) : [];
    $: span = SIZE - PAD * 2;
</script>

<section class="cal">
    <h3>Calibration <span class="sub">— your confidence vs. reality</span></h3>

    {#if failed}
        <p class="muted">Calibration unavailable.</p>
    {:else if !cal}
        <p class="muted">Loading…</p>
    {:else if cal.abstained || cal.attempts < 1 || points.length === 0}
        <p class="muted">
            Not enough calibration data yet. Rate your confidence (Sure / Think / Guess)
            before answering timed problems to unlock your reliability curve — it abstains
            rather than draw a curve from too few bets.
        </p>
    {:else}
        <div class="chartrow">
            <svg viewBox={`0 0 ${SIZE} ${SIZE}`} class="chart" role="img"
                aria-label="Reliability diagram: stated confidence versus actual accuracy">
                <!-- overconfidence region (below the diagonal) -->
                <polygon
                    points={`${PAD},${SIZE - PAD} ${SIZE - PAD},${SIZE - PAD} ${SIZE - PAD},${PAD}`}
                    class="overconf"
                />
                <!-- perfect-calibration diagonal -->
                <line x1={PAD} y1={SIZE - PAD} x2={SIZE - PAD} y2={PAD} class="diag" />
                <!-- axes -->
                <line x1={PAD} y1={PAD} x2={PAD} y2={SIZE - PAD} class="axis" />
                <line x1={PAD} y1={SIZE - PAD} x2={SIZE - PAD} y2={SIZE - PAD} class="axis" />
                {#each points as p (p.bin.confidence)}
                    <circle cx={p.cx} cy={p.cy} r={p.r} class:over={p.overconfident} class="pt">
                        <title>{Math.round(p.bin.confidence * 100)}% stated → {Math.round(
                            p.bin.accuracy * 100,
                        )}% actual (n={p.bin.n})</title>
                    </circle>
                {/each}
                <text x={PAD} y={SIZE - 6} class="lbl">guess</text>
                <text x={SIZE - PAD} y={SIZE - 6} class="lbl end">sure</text>
                <text x={6} y={PAD + 4} class="lbl" transform={`rotate(-90 6 ${PAD + 4})`}>accuracy</text>
            </svg>
            <dl class="stats">
                <div><dt>Brier</dt><dd>{cal.brier.toFixed(3)}</dd></div>
                <div><dt>ECE</dt><dd>{Math.round(cal.ece * 100)}%</dd></div>
                <div><dt>Bets</dt><dd>{cal.attempts}</dd></div>
                <div class="hint">
                    Dots below the line = overconfident (you bet higher than you scored).
                    Lower Brier/ECE = better calibrated. Self-reported until interactive grading.
                </div>
            </dl>
        </div>
    {/if}
</section>

<style>
    .cal {
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
    .chartrow {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    @media (min-width: 560px) {
        .chartrow {
            flex-direction: row;
            align-items: center;
        }
    }
    .chart {
        width: 240px;
        max-width: 100%;
        flex: none;
        background: #0a0d11;
        border: 1px solid var(--line, #232a33);
        border-radius: 6px;
    }
    .overconf {
        fill: rgba(180, 87, 63, 0.1);
    }
    .diag {
        stroke: var(--muted, #7c8794);
        stroke-width: 1;
        stroke-dasharray: 4 3;
    }
    .axis {
        stroke: var(--line, #232a33);
        stroke-width: 1;
    }
    .pt {
        fill: rgba(90, 169, 106, 0.85);
        stroke: #0a0d11;
        stroke-width: 1;
    }
    .pt.over {
        fill: rgba(180, 87, 63, 0.9);
    }
    .lbl {
        fill: var(--muted, #7c8794);
        font-size: 9px;
        font-family: var(--disp, sans-serif);
    }
    .lbl.end {
        text-anchor: end;
    }
    .stats {
        margin: 0;
        display: flex;
        flex-wrap: wrap;
        gap: 8px 20px;
        align-content: flex-start;
    }
    .stats > div:not(.hint) {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    dt {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--muted, #7c8794);
    }
    dd {
        margin: 0;
        font-size: 18px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
    }
    .hint {
        flex-basis: 100%;
        color: var(--muted, #7c8794);
        font-size: 12px;
        line-height: 1.45;
    }
</style>
