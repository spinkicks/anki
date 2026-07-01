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
