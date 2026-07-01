<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    // weakestTimed = label of the lowest-recall timed topic, or null if nothing
    // has been timed yet. Drives the NEXT SEGMENT hint honestly.
    export let weakestTimed: string | null = null;

    // The desktop/Android shell wires the real study-session launch; we expose
    // onStartRun as a prop. The default guards `pycmd` (injected by the Anki
    // webview, not declared in the SvelteKit TS scope) so it is a no-op outside
    // a webview (e.g. dev server / tests).
    export let onStartRun: () => void = () => {
        (globalThis as { pycmd?: (cmd: string) => void }).pycmd?.("startrun");
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
    .action {
        display: flex;
        align-items: center;
        gap: 20px;
        padding: 22px 28px;
        border-top: 1px solid var(--line);
        margin-top: 8px;
    }
    .run {
        font-family: var(--mono);
        font-weight: 600;
        font-size: 14px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        background: var(--pace);
        color: var(--ink);
        border: none;
        padding: 14px 26px;
        cursor: pointer;
    }
    .run:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
    .next {
        font-family: var(--mono);
        font-size: 12px;
        color: var(--muted);
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .next b {
        color: var(--fg);
        font-weight: 500;
    }
</style>
