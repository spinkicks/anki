<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { GRE_MAX, GRE_MIN, ScoreScale } from "@speedrun/data";

    // point/lower/upper are in the units named by `scale`:
    //  - UNIT (default): 0..1 probability/proportion -> rendered ×100 as "%".
    //  - GRE_200_990: raw 200–990 scaled score -> rendered as integers, no "%".
    // Existing recall callers omit `scale`, so they keep the UNIT behavior.
    export let lower: number;
    export let upper: number;
    export let point: number;
    export let scale: ScoreScale = ScoreScale.UNIT;

    $: gre = scale === ScoreScale.GRE_200_990;
    // Track min/max in the value's own units; UNIT is the 0..1 track.
    $: min = gre ? GRE_MIN : 0;
    $: max = gre ? GRE_MAX : 1;
    // Normalized [0,1] position on the track (clamped so a slightly out-of-range
    // engine value can't overflow the bar).
    const norm = (v: number, lo: number, hi: number) =>
        Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    $: lPos = norm(lower, min, max);
    $: uPos = norm(upper, min, max);
    $: pPos = norm(point, min, max);
    // Human labels: integers on the GRE scale, whole percents on the UNIT scale.
    const label = (v: number) =>
        gre ? String(Math.round(v)) : `${Math.round(v * 100)}%`;
    $: text = `${label(lower)}–${label(upper)}`;
</script>

<div class="range" title={text}>
    <div class="track">
        <div
            class="fill"
            style={`left:${lPos * 100}%;width:${(uPos - lPos) * 100}%`}
        ></div>
        <div class="marker" style={`left:${pPos * 100}%`}></div>
    </div>
    <span class="nums">{text}</span>
</div>

<style>
    /* Mobile-first base: wrap so track goes full-width, nums wrap below */
    .range {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }
    .track {
        position: relative;
        /* Mobile: full width */
        width: 100%;
        flex: none;
        height: 8px;
        background: #0a0d11;
        border: 1px solid var(--line);
    }
    /* Desktop restore: track flex-shrinkable, nums beside it */
    @media (min-width: 768px) {
        .range {
            flex-wrap: nowrap;
        }
        .track {
            flex: 1;
            width: auto;
        }
    }
    .fill {
        position: absolute;
        top: 0;
        height: 100%;
        background: rgba(230, 234, 239, 0.18);
    }
    .marker {
        position: absolute;
        top: -2px;
        width: 2px;
        height: 12px;
        background: var(--pace);
    }
    .nums {
        font-variant-numeric: tabular-nums;
        min-width: 64px;
    }
</style>
