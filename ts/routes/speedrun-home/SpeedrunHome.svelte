<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Speedrun Home — "The Run". Branded flat/sharp home screen. Composes the run
header, headline stat row, the signature split rows, and the action bar. All
dynamic content is honest/derived (no fake session/PB); a fresh deck abstains
calmly. Reuses the frozen SpeedrunService RPCs via @speedrun/data.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import ActionBar from "./ActionBar.svelte";
    import { type HomeView, loadHome } from "./data";
    import RunHeader from "./RunHeader.svelte";
    import Splits from "./Splits.svelte";
    import StatRow from "./StatRow.svelte";

    let view: HomeView | null = null;
    let loading = true;
    let error = "";
    // "" -> profile loaded; set when loadHome returns null (no matching profile).
    let noProfile = false;

    async function refresh() {
        loading = true;
        error = "";
        noProfile = false;
        try {
            view = await loadHome("gre_math");
            if (!view) {
                noProfile = true;
            }
        } catch (e) {
            error = String(e);
        } finally {
            loading = false;
        }
    }
    onMount(refresh);
</script>

<div class="app">
    {#if loading}
        <div class="spinner">Loading…</div>
    {:else if error}
        <div class="empty">{error}</div>
    {:else if noProfile}
        <div class="empty">
            No cards found for this exam profile — import the seed deck.
        </div>
    {:else if view}
        <RunHeader timedReviewsTotal={view.timedReviewsTotal} />
        <StatRow coverage={view.coverage} memoryVerified={view.memoryVerified} />
        <Splits segments={view.segments} />
        <ActionBar weakestTimed={view.weakestTimed} />
        <div class="foot">
            Speedrun measures what you can recall — not a guessed score. Ranges are 95%
            intervals; untimed segments abstain by design.
        </div>
        <div class="memory-link">
            <a href="/speedrun-memory">MEMORY ▸</a>
        </div>
    {/if}
</div>

<style>
    /* Design tokens (flat/sharp: no rounded corners, no gradients, no glow). */
    .app {
        /* Fonts (offline-safe): named fonts first so a bundled OFL woff2 would
           activate automatically later; strong system fallbacks otherwise. We do
           NOT fetch fonts from the network (webview must work offline). */
        --disp: "Space Grotesk", "Segoe UI", system-ui, sans-serif;
        --mono:
            "IBM Plex Mono", ui-monospace, "Cascadia Mono", "Segoe UI Mono",
            "Roboto Mono", monospace;

        --ink: #0b0e12;
        --panel: #12161c;
        --line: #232a33;
        --fg: #e6eaef;
        --muted: #7c8794;
        --pace: #e8b23a;

        /* Mobile-first base: full width, no side borders */
        width: 100%;
        min-height: 100vh;
        background: var(--ink);
        color: var(--fg);
        font-family: var(--disp);
        -webkit-font-smoothing: antialiased;
    }
    /* Desktop restore: constrained width + side borders */
    @media (min-width: 768px) {
        .app {
            max-width: 960px;
            margin: 0 auto;
            border-left: 1px solid var(--line);
            border-right: 1px solid var(--line);
        }
    }
    .app :global(*) {
        box-sizing: border-box;
    }

    .spinner,
    .empty {
        font-family: var(--mono);
        font-size: 13px;
        letter-spacing: 0.08em;
        color: var(--muted);
        padding: 28px;
        text-transform: uppercase;
    }

    .foot {
        padding: 14px 28px 26px;
        font-family: var(--mono);
        font-size: 10px;
        color: var(--muted);
        letter-spacing: 0.1em;
        border-top: 1px solid var(--line);
        text-transform: uppercase;
    }
    .memory-link {
        padding: 0 28px 26px;
    }
    .memory-link a {
        font-family: var(--mono);
        font-size: 11px;
        letter-spacing: 0.18em;
        color: var(--muted);
        text-decoration: none;
        text-transform: uppercase;
    }
    .memory-link a:hover,
    .memory-link a:focus-visible {
        color: var(--fg);
    }
</style>
