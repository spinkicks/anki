<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Speedrun Home — "The Run". Branded flat/sharp home screen. Composes the run
header, headline stat row, the signature split rows, and the action bar. All
dynamic content is honest/derived (no fake session/PB); a fresh deck abstains
calmly. Reuses the frozen SpeedrunService RPCs via @speedrun/data.
-->
<script lang="ts">
    import { onDestroy, onMount } from "svelte";

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

    // Inline START RUN status banner. The Qt shell drives this via web.eval
    // (window.speedrunStartStatus) when it can't launch study: "importNeeded"
    // (exam/problem deck missing), "caughtUp" (nothing due; optional n = new
    // cards that unlock next), "noActiveProblems" (problem bank imported but all
    // suspended — unsuspend, don't import), or "mockFailed" (the timed mini-mock
    // build found no eligible problems). Null = hidden. pycmd is injected by the
    // Anki webview (not in the SvelteKit TS scope), so we cast when reaching for it.
    type StartStatus = { state: string; n?: number };
    let startStatus: StartStatus | null = null;

    function fire(cmd: string) {
        // Desktop aliases pycmd===bridgeCommand; Android's PageFragment injects
        // ONLY bridgeCommand. Fire exactly one, preferring pycmd — mirrors
        // ActionBar so the status-banner actions work on Android too (were dead).
        const g = globalThis as {
            pycmd?: (cmd: string) => void;
            bridgeCommand?: (cmd: string) => void;
        };
        (g.pycmd ?? g.bridgeCommand)?.(cmd);
    }

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

    onMount(() => {
        (
            globalThis as {
                speedrunStartStatus?: (state: string, n?: number) => void;
            }
        ).speedrunStartStatus = (state, n) => {
            startStatus = { state, n };
        };
        refresh();
    });
    onDestroy(() => {
        delete (globalThis as { speedrunStartStatus?: unknown }).speedrunStartStatus;
    });
</script>

<div class="app">
    {#if startStatus}
        <div class="startstatus" role="status">
            <div class="startstatus-body">
                {#if startStatus.state === "importNeeded"}
                    <span class="startstatus-text">
                        Import the GRE exam deck to start a run.
                    </span>
                    <button
                        class="startstatus-btn"
                        on:click={() => fire("startrun:import")}
                    >
                        Import deck
                    </button>
                {:else if startStatus.state === "caughtUp"}
                    <span class="startstatus-text">
                        All caught up for today.{#if startStatus.n && startStatus.n > 0}{" "}{startStatus.n}
                            new cards will unlock next.{/if}
                    </span>
                    <button
                        class="startstatus-btn"
                        on:click={() => fire("startrun:customstudy")}
                    >
                        Custom Study
                    </button>
                {:else if startStatus.state === "mockFailed"}
                    <!-- Honest failure state: the Qt shell couldn't build the
                         timed mini-mock (e.g. no eligible problem cards). No
                         fake success — tell the user plainly. -->
                    <span class="startstatus-text">
                        Couldn't start a timed mini-mock — no eligible problems found.
                        Import or unsuspend the GRE problem bank and try again.
                    </span>
                    <button
                        class="startstatus-btn"
                        on:click={() => fire("startrun:import")}
                    >
                        Import deck
                    </button>
                {:else if startStatus.state === "noActiveProblems"}
                    <!-- Honest state: the GRE problem bank IS imported but every
                         problem card is suspended, so a timed mini-mock has
                         nothing to draw. Don't tell them to import (dishonest) —
                         tell them to unsuspend. Informational only: there's no
                         clean in-app unsuspend action from here, so no button
                         (mirrors the mockFailed/caughtUp informational states;
                         we do NOT invent a bridge command). -->
                    <span class="startstatus-text">
                        Your GRE problem bank is all suspended — unsuspend problems
                        (Browse ▸ select ▸ Toggle Suspend) to run a timed mini-mock.
                    </span>
                {/if}
            </div>
            <button
                class="startstatus-close"
                aria-label="Dismiss"
                on:click={() => (startStatus = null)}
            >
                ✕
            </button>
        </div>
    {/if}
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
        <StatRow
            coverage={view.coverage}
            memoryVerified={view.memoryVerified}
            performance={view.performance}
            readiness={view.readiness}
            calibration={view.calibration}
        />
        <Splits segments={view.segments} />
        <ActionBar weakestTimed={view.weakestTimed} />
        <div class="foot">
            <!-- §7d abstention framing: make the "we don't guess" ethos explicit
                 so a "—" cell reads as a deliberate abstain, not missing data. -->
            Speedrun measures what you can recall — not a guessed score. Ranges are 95%
            intervals; untimed segments show "—" and abstain by design rather than
            guess.
            <!-- §7b survivorship-bias one-liner. No goal/timeline UI exists to host
                 this, so it lives here as a general caveat on the pace framing. -->
            Pace reflects your run so far — not a promised outcome; results vary.
        </div>
        <div class="memory-link">
            <a href="/speedrun-memory">MEMORY ▸</a>
        </div>
    {/if}
</div>

<style>
    /* Design tokens (flat/sharp: no rounded corners, no gradients, no glow). */
    .app {
        /* Fonts (offline-safe): Manrope is self-hosted (OFL woff2 bundled in
           the SvelteKit _app output via base.scss @font-face — 500 body/numerals,
           800 wordmark/headings); strong system fallbacks otherwise. We do NOT
           fetch fonts from the network (webview must work offline). */
        --disp: "Manrope", "Segoe UI", system-ui, sans-serif;
        --mono:
            "IBM Plex Mono", ui-monospace, "Cascadia Mono", "Segoe UI Mono",
            "Roboto Mono", monospace;

        --ink: #0b0e12;
        --panel: #12161c;
        --line: #232a33;
        --fg: #e6eaef;
        --muted: #7c8794;
        --pace: #f4f7fa;

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
        font-family: var(--disp);
        font-size: 13px;
        letter-spacing: 0.08em;
        color: var(--muted);
        padding: 28px;
        text-transform: uppercase;
    }

    .foot {
        padding: 14px 28px 26px;
        font-family: var(--disp);
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
        font-family: var(--disp);
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

    /* START RUN status banner (flat/sharp; tokens only). Driven by the Qt
       shell via window.speedrunStartStatus when it can't launch study. */
    .startstatus {
        display: flex;
        align-items: stretch;
        gap: 12px;
        padding: 12px 16px;
        background: var(--panel);
        border-bottom: 1px solid var(--line);
        border-left: 3px solid var(--pace);
    }
    @media (min-width: 768px) {
        .startstatus {
            padding: 14px 28px;
        }
    }
    .startstatus-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 10px;
        align-items: flex-start;
    }
    @media (min-width: 768px) {
        .startstatus-body {
            flex-direction: row;
            align-items: center;
            gap: 16px;
        }
    }
    .startstatus-text {
        font-family: var(--disp);
        font-size: 12px;
        letter-spacing: 0.06em;
        color: var(--fg);
        text-transform: uppercase;
        line-height: 1.5;
    }
    .startstatus-btn {
        font-family: var(--disp);
        font-weight: 500;
        font-size: 12px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        background: var(--pace);
        color: var(--ink);
        border: none;
        /* Full-width, ≥44px tall touch target on mobile. */
        width: 100%;
        min-height: 44px;
        padding: 12px 18px;
        cursor: pointer;
    }
    @media (min-width: 768px) {
        .startstatus-btn {
            width: auto;
            min-height: 0;
            padding: 10px 18px;
        }
    }
    .startstatus-btn:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
    .startstatus-close {
        flex: 0 0 auto;
        font-family: var(--disp);
        font-size: 14px;
        line-height: 1;
        background: transparent;
        color: var(--muted);
        border: 1px solid var(--line);
        /* ≥44px touch target. */
        min-width: 44px;
        min-height: 44px;
        cursor: pointer;
    }
    .startstatus-close:hover,
    .startstatus-close:focus-visible {
        color: var(--fg);
    }
    .startstatus-close:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
</style>
