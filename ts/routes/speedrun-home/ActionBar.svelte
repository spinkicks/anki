<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    // weakestTimed = label of the lowest-recall timed topic, or null if nothing
    // has been timed yet. Drives the NEXT SEGMENT hint honestly.
    export let weakestTimed: string | null = null;

    // The desktop/Android shell wires the real study-session launch; we expose
    // onStartRun as a prop. IMPORTANT: the desktop Qt webview aliases `pycmd`
    // and `bridgeCommand` to the SAME function (qt/aqt/webview.py:93), so firing
    // both would dispatch "startrun" TWICE (double reviewer launch). Android
    // injects only `bridgeCommand`. So fire exactly ONE, preferring `pycmd`;
    // outside a webview (dev server / tests) both are undefined and it's a no-op.
    export let onStartRun: () => void = () => {
        const g = globalThis as {
            pycmd?: (cmd: string) => void;
            bridgeCommand?: (cmd: string) => void;
        };
        (g.pycmd ?? g.bridgeCommand)?.("startrun");
    };
</script>

<div class="action">
    <button class="run" on:click={onStartRun}>► START RUN</button>
    {#if weakestTimed}
        <div class="next">
            NEXT SEGMENT · <b>{weakestTimed}</b>
            — weakest timed topic
        </div>
    {:else}
        <div class="next">— begin timing to set a pace</div>
    {/if}
</div>

<style>
    /* Mobile-first base: stacked column, full-width button */
    .action {
        display: flex;
        align-items: stretch;
        flex-direction: column;
        gap: 12px;
        padding: 16px;
        border-top: 1px solid var(--line);
        margin-top: 8px;
    }
    /* Desktop restore: horizontal row */
    @media (min-width: 768px) {
        .action {
            flex-direction: row;
            align-items: center;
            gap: 20px;
            padding: 22px 28px;
        }
    }
    .run {
        font-family: var(--disp);
        font-weight: 600;
        font-size: 14px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        background: var(--pace);
        color: var(--ink);
        border: none;
        /* Mobile: full width, tall enough for 44px touch target */
        width: 100%;
        padding: 16px;
        cursor: pointer;
    }
    /* Desktop restore: auto width, original padding */
    @media (min-width: 768px) {
        .run {
            width: auto;
            padding: 14px 26px;
        }
    }
    .run:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
    /* Mobile: centered; desktop restore: default (left) */
    .next {
        font-family: var(--disp);
        font-size: 12px;
        color: var(--muted);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        text-align: center;
    }
    @media (min-width: 768px) {
        .next {
            text-align: left;
        }
    }
    .next b {
        color: var(--fg);
        font-weight: 500;
    }
</style>
