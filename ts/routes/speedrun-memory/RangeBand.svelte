<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    export let lower: number; // 0..1
    export let upper: number; // 0..1
    export let point: number; // 0..1
</script>

<div class="range" title={`${Math.round(lower * 100)}–${Math.round(upper * 100)}%`}>
    <div class="track">
        <div
            class="fill"
            style={`left:${lower * 100}%;width:${(upper - lower) * 100}%`}
        ></div>
        <div class="marker" style={`left:${point * 100}%`}></div>
    </div>
    <span class="nums">{Math.round(lower * 100)}–{Math.round(upper * 100)}%</span>
</div>

<style>
    .range {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .track {
        position: relative;
        flex: 1;
        height: 8px;
        background: var(--frame-bg, #e0e0e0);
        border-radius: 4px;
    }
    .fill {
        position: absolute;
        top: 0;
        height: 100%;
        background: var(--accent, #8aa);
        border-radius: 4px;
    }
    .marker {
        position: absolute;
        top: -2px;
        width: 2px;
        height: 12px;
        background: var(--fg, #333);
    }
    .nums {
        font-variant-numeric: tabular-nums;
        min-width: 64px;
    }
</style>
