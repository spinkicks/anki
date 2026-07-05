<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

Speedrun shell — the single shared frame for every Speedrun page (Home, The Map,
Memory). It owns the design tokens ONCE (previously copy-pasted into each page)
and renders a persistent left sidebar for navigation + practice actions, with the
page content in a <slot>. Custom properties cascade to the slotted content, so
the pages inherit --ink/--pace/--disp/etc. from here.

Responsive: desktop (>=768px) shows the real left sidebar; mobile collapses it to
a compact top bar (nav only — the phone's Home already surfaces Start Run, and a
wrapped row of action buttons would be janky on a 360px screen).

Bridge actions (Start Run / Mini-mock) fire exactly one of pycmd/bridgeCommand
(desktop aliases them; Android injects only bridgeCommand). They are DISABLED when
no native bridge is present (dev server / tests / a preview), so a click is never a
silent no-op there.
-->
<script lang="ts">
    import { onMount } from "svelte";

    // Which nav item is the current page (drives the active highlight).
    export let active: "home" | "map" | "memory" = "home";

    // True only inside a real Anki webview (desktop Qt or Android PageFragment),
    // where pycmd/bridgeCommand exist. Elsewhere the practice actions disable.
    let hasBridge = false;

    onMount(() => {
        const g = globalThis as {
            pycmd?: unknown;
            bridgeCommand?: unknown;
        };
        hasBridge = typeof g.pycmd === "function" || typeof g.bridgeCommand === "function";
    });

    function fire(cmd: string): void {
        // Single dispatch, preferring pycmd (desktop aliases pycmd===bridgeCommand,
        // so firing both would double-dispatch). No-op outside a webview.
        const g = globalThis as {
            pycmd?: (c: string) => void;
            bridgeCommand?: (c: string) => void;
        };
        (g.pycmd ?? g.bridgeCommand)?.(cmd);
    }
</script>

<div class="shell">
    <nav class="sidebar" aria-label="Speedrun navigation">
        <a class="brand" href="/speedrun-home" aria-label="Speedrun home">
            <span class="brandmark">SPEED<span class="pace">RUN</span></span>
        </a>

        <div class="navgroup">
            <span class="navlabel">Navigate</span>
            <a
                class="navitem"
                class:active={active === "home"}
                href="/speedrun-home"
                aria-current={active === "home" ? "page" : undefined}
            >
                Home
            </a>
            <a
                class="navitem"
                class:active={active === "map"}
                href="/speedrun-map"
                aria-current={active === "map" ? "page" : undefined}
            >
                The Map
            </a>
            <a
                class="navitem"
                class:active={active === "memory"}
                href="/speedrun-memory"
                aria-current={active === "memory" ? "page" : undefined}
            >
                Memory
            </a>
        </div>

        <div class="navgroup practice">
            <span class="navlabel">Practice</span>
            <button
                class="act run"
                disabled={!hasBridge}
                title={hasBridge ? "" : "Open Speedrun in the app to start a run"}
                on:click={() => fire("startrun")}
            >
                ► Start Run
            </button>
            <button
                class="act"
                disabled={!hasBridge}
                title={hasBridge ? "" : "Open Speedrun in the app to run a mini-mock"}
                on:click={() => fire("minimock")}
            >
                Mini-mock
            </button>
        </div>

        <div class="foot">
            Honest scores only — ranges are 95% intervals; "—" means not enough data
            yet, never a guess.
        </div>
    </nav>

    <main class="content"><slot /></main>
</div>

<style>
    .shell {
        /* Single source of truth for the Speedrun design tokens (self-hosted
           Manrope via base.scss @font-face; near-white #F4F7FA accent). These
           cascade to the slotted page content, so pages no longer redefine them. */
        --ink: #0b0e12;
        --panel: #12161c;
        --line: #232a33;
        --fg: #e6eaef;
        --muted: #7c8794;
        --pace: #f4f7fa;
        --disp: "Manrope", "Segoe UI", system-ui, sans-serif;
        --mono:
            "IBM Plex Mono", ui-monospace, "Cascadia Mono", "Segoe UI Mono",
            "Roboto Mono", monospace;

        display: flex;
        flex-direction: column;
        min-height: 100vh;
        background: var(--ink);
        color: var(--fg);
        font-family: var(--disp);
        -webkit-font-smoothing: antialiased;
    }
    .shell :global(*) {
        box-sizing: border-box;
    }

    /* ---- Mobile-first: sidebar becomes a compact top bar (nav only). ---- */
    .sidebar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px 8px;
        padding: 10px 12px;
        background: var(--panel);
        border-bottom: 1px solid var(--line);
    }
    .brand {
        text-decoration: none;
        color: var(--fg);
        margin-right: 4px;
    }
    .brandmark {
        display: inline-flex;
        font-weight: 800;
        font-size: 18px;
        letter-spacing: 0.02em;
    }
    .pace {
        color: var(--pace);
    }
    .navgroup {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
    }
    .navlabel {
        display: none;
    }
    .navitem {
        display: inline-flex;
        align-items: center;
        min-height: 40px;
        padding: 6px 10px;
        font-family: var(--disp);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
        text-decoration: none;
        border: 1px solid transparent;
    }
    .navitem:hover,
    .navitem:focus-visible {
        color: var(--fg);
    }
    .navitem.active {
        color: var(--fg);
        border-color: var(--line);
        background: var(--ink);
    }
    /* Practice actions are hidden on the phone top bar (Home surfaces Start Run
       there); they appear in the desktop sidebar. */
    .practice {
        display: none;
    }
    .act {
        min-height: 40px;
        padding: 6px 12px;
        font-family: var(--disp);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--fg);
        background: transparent;
        border: 1px solid var(--line);
        cursor: pointer;
    }
    .act.run {
        background: var(--pace);
        color: var(--ink);
        border-color: var(--pace);
    }
    .act:hover:not(:disabled) {
        border-color: var(--pace);
    }
    .act:focus-visible {
        outline: 2px solid var(--fg);
        outline-offset: 2px;
    }
    .act:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .foot {
        display: none;
    }
    .content {
        flex: 1;
        min-width: 0;
    }

    /* ---- Desktop: real persistent left sidebar. ---- */
    @media (min-width: 768px) {
        .shell {
            flex-direction: row;
        }
        .sidebar {
            flex-direction: column;
            flex-wrap: nowrap;
            align-items: stretch;
            gap: 2px;
            width: 220px;
            flex: none;
            padding: 22px 14px;
            border-bottom: none;
            border-right: 1px solid var(--line);
            position: sticky;
            top: 0;
            align-self: flex-start;
            height: 100vh;
        }
        .brand {
            margin: 0 0 16px 4px;
        }
        .navlabel {
            display: block;
            margin: 16px 4px 4px;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--muted);
        }
        .navgroup {
            flex-direction: column;
            align-items: stretch;
            gap: 2px;
        }
        .practice {
            display: flex;
        }
        .navitem {
            justify-content: flex-start;
        }
        .act {
            width: 100%;
            justify-content: center;
            text-align: center;
            margin-top: 6px;
        }
        .foot {
            display: block;
            margin-top: auto;
            padding-top: 16px;
            border-top: 1px solid var(--line);
            font-size: 10px;
            letter-spacing: 0.08em;
            line-height: 1.6;
            text-transform: uppercase;
            color: var(--muted);
        }
    }
</style>
