<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Readiness gauge — the honest 200–990 score as a number line with the conformal
range drawn as a band. Below the data threshold it abstains (no needle, no
number), and it shows no percentile (we have no ETS norm table).
-->
<script lang="ts">
    import { GRE_MAX, GRE_MIN } from "@speedrun/data";

    export let point: number;
    export let lower: number;
    export let upper: number;
    export let abstained: boolean;
    export let unlockHuman = "";

    const norm = (v: number) =>
        Math.max(0, Math.min(1, (v - GRE_MIN) / (GRE_MAX - GRE_MIN)));
    $: lo = norm(lower);
    $: hi = norm(upper);
    $: pt = norm(point);
</script>

<section class="gauge" class:abstained>
    <div class="head">
        <span class="ttl">Readiness</span>
        {#if abstained}
            <span class="abs">— insufficient data</span>
        {:else}
            <span class="score">{Math.round(point)}<small>/990</small></span>
        {/if}
    </div>

    <div class="track">
        {#if !abstained}
            <div class="band" style={`left:${lo * 100}%;width:${(hi - lo) * 100}%`}></div>
            <div class="needle" style={`left:${pt * 100}%`}></div>
        {/if}
    </div>

    <div class="scale">
        <span>200</span>
        <span>990</span>
    </div>

    {#if abstained}
        <p class="unlock">{unlockHuman || "Answer more timed mini-mocks to unlock a readiness range."}</p>
    {:else}
        <p class="rng">95% range: {Math.round(lower)}–{Math.round(upper)} · calibrated, widens when data is thin</p>
    {/if}
</section>

<style>
    .gauge {
        margin: 12px 0 4px;
        padding: 12px 14px;
        background: var(--panel, #12161c);
        border: 1px solid var(--line, #232a33);
        border-radius: 8px;
    }
    .head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 10px;
    }
    .ttl {
        font-weight: 800;
        font-size: 14px;
    }
    .score {
        font-weight: 800;
        font-size: 24px;
        font-variant-numeric: tabular-nums;
        color: var(--pace, #f4f7fa);
    }
    .score small {
        font-size: 13px;
        color: var(--muted, #7c8794);
        font-weight: 500;
    }
    .abs {
        color: var(--muted, #7c8794);
        font-weight: 700;
        font-size: 13px;
    }
    .track {
        position: relative;
        height: 12px;
        background: #0a0d11;
        border: 1px solid var(--line, #232a33);
        border-radius: 3px;
    }
    .band {
        position: absolute;
        top: 0;
        height: 100%;
        background: rgba(230, 234, 239, 0.18);
    }
    .needle {
        position: absolute;
        top: -3px;
        width: 3px;
        height: 18px;
        background: var(--pace, #f4f7fa);
        transform: translateX(-1px);
    }
    .scale {
        position: relative;
        display: flex;
        justify-content: space-between;
        margin-top: 8px;
        font-size: 11px;
        color: var(--muted, #7c8794);
        font-variant-numeric: tabular-nums;
    }
    .unlock,
    .rng {
        margin: 10px 0 0;
        font-size: 12px;
        color: var(--muted, #7c8794);
        line-height: 1.45;
    }
</style>
