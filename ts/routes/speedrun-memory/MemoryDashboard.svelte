<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { onMount } from "svelte";

    import {
        type ExamProfile,
        loadCoverage,
        loadProfile,
        loadRows,
        loadScaffoldMap,
        type Row,
        type TopicScaffoldRow,
    } from "./data";
    import TopicRow from "./TopicRow.svelte";

    let profile: ExamProfile | null = null;
    let rows: Row[] = [];
    let coverage = { covered: 0, total: 0, percent: 0 };
    let scaffold: Map<string, TopicScaffoldRow> = new Map();
    let loading = true;
    let error = "";
    let weakestFirst = false;
    let updated = "";

    async function refresh() {
        loading = true;
        error = "";
        try {
            profile = await loadProfile("gre_math");
            if (!profile) {
                error = "No cards found for this exam profile — import the seed deck.";
                return;
            }
            [rows, coverage, scaffold] = await Promise.all([
                loadRows(profile),
                loadCoverage(profile),
                loadScaffoldMap(profile),
            ]);
            updated = new Date().toLocaleTimeString();
        } catch (e) {
            error = String(e);
        } finally {
            loading = false;
        }
    }
    onMount(refresh);

    // group leaf rows under their root container; sort within group.
    $: groups = (() => {
        if (!profile) {
            return [];
        }
        const containers = rows.filter((r) => r.isContainer);
        return containers.map((c) => {
            let leaves = rows.filter((r) => !r.isContainer && r.root === c.id);
            leaves = [...leaves].sort((a, b) =>
                weakestFirst
                    ? (a.abstained ? 2 : a.avgRecall) - (b.abstained ? 2 : b.avgRecall)
                    : b.weight - a.weight,
            );
            return { header: c, leaves };
        });
    })();
</script>

<div class="memory">
    <header>
        <div class="titlebar">
            <h1>Memory</h1>
            <button on:click={refresh}>Refresh</button>
        </div>
        <p class="explain">
            Your recalled memory by topic. Memory ≠ readiness — this measures what you
            retain, not whether you can solve timed problems.
        </p>
        <p class="coverage">
            Coverage: {coverage.covered} / {coverage.total} required topics present ({Math.round(
                coverage.percent,
            )}%)
            <span class="updated">Updated {updated}</span>
        </p>
        <label class="sort">
            <input type="checkbox" bind:checked={weakestFirst} />
            Weakest first
        </label>
    </header>

    {#if loading}
        <div class="spinner">Loading…</div>
    {:else if error}
        <div class="empty">{error}</div>
    {:else}
        <table>
            <thead>
                <tr>
                    <th>TOPIC (weight)</th>
                    <th>RECALL</th>
                    <th>RANGE (95%)</th>
                    <th>DATA</th>
                    <th>
                        PERFORMANCE <span class="scaffolding-note">(scaffolding)</span>
                    </th>
                    <th>
                        READINESS <span class="scaffolding-note">(scaffolding)</span>
                    </th>
                </tr>
            </thead>
            {#each groups as g}
                <tbody>
                    <tr class="grouphdr"><td colspan="6">{g.header.label}</td></tr>
                    {#each g.leaves as row (row.id)}
                        <TopicRow {row} scaffold={scaffold.get(row.id)} />
                    {/each}
                </tbody>
            {/each}
        </table>
    {/if}
</div>

<style>
    /* Design tokens — mirror "The Run" dark palette so Memory matches Home. */
    .memory {
        /* Manrope self-hosted (OFL woff2 bundled offline via base.scss
           @font-face — 500 body/numerals, 800 headings). Mirrors Home. */
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

        /* Mobile-first base: full width, compact padding */
        width: 100%;
        padding: 12px;
        background: var(--ink);
        color: var(--fg);
        font-family: var(--disp);
        -webkit-font-smoothing: antialiased;
    }
    /* Desktop restore: constrained max-width, original padding, side borders */
    @media (min-width: 768px) {
        .memory {
            max-width: 820px;
            margin: 0 auto;
            padding: 16px;
            border-left: 1px solid var(--line);
            border-right: 1px solid var(--line);
        }
    }
    .titlebar {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .titlebar h1 {
        font-family: var(--disp);
        font-size: 18px;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--fg);
    }
    .titlebar button {
        font-family: var(--disp);
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
        background: none;
        border: 1px solid var(--line);
        cursor: pointer;
        padding: 6px 10px;
    }
    .titlebar button:hover,
    .titlebar button:focus-visible {
        color: var(--fg);
        border-color: var(--muted);
    }
    .explain {
        color: var(--muted);
        font-size: 13px;
    }
    .coverage {
        font-weight: 500;
        color: var(--fg);
        font-size: 13px;
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
    }
    .updated {
        float: right;
        font-weight: 500;
        color: var(--muted);
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
    }
    /* "Weakest first" label: 44px touch target on mobile */
    .sort {
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 44px;
        font-family: var(--disp);
        font-size: 12px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--muted);
        cursor: pointer;
    }
    .sort:hover {
        color: var(--fg);
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
    table {
        width: 100%;
        border-collapse: collapse;
    }

    /* Mobile: hide thead */
    thead {
        display: none;
    }
    /* Desktop restore: show thead */
    @media (min-width: 768px) {
        thead {
            display: table-header-group;
        }
    }

    th {
        text-align: left;
        font-size: 0.8em;
        color: var(--muted);
        border-bottom: 1px solid var(--line);
        padding: 6px 4px;
        font-family: var(--disp);
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .scaffolding-note {
        font-size: 0.85em;
        font-weight: 500;
        color: var(--muted);
        font-style: italic;
    }

    /* Mobile: td padding (base) */
    :global(.memory td) {
        padding: 6px 4px;
        border-bottom: 1px solid var(--line);
    }

    /* Mobile: tbody rows as stacked cards */
    :global(.memory tbody tr:not(.grouphdr)) {
        display: block;
        border-bottom: 2px solid var(--line);
        margin-bottom: 12px;
        padding: 12px;
        background: var(--panel);
    }
    :global(.memory tbody tr:not(.grouphdr) td) {
        display: block;
        border-bottom: none;
        padding: 3px 0;
    }

    /* Desktop restore: normal table-row / table-cell */
    @media (min-width: 768px) {
        :global(.memory tbody tr:not(.grouphdr)) {
            display: table-row;
            border-bottom: none;
            margin-bottom: 0;
            padding: 0;
            background: transparent;
        }
        :global(.memory tbody tr:not(.grouphdr) td) {
            display: table-cell;
            padding: 6px 4px;
            border-bottom: 1px solid var(--line);
        }
    }

    /* Mobile: compact group header */
    .grouphdr td {
        font-weight: 800;
        padding-top: 8px;
        color: var(--fg);
        font-family: var(--disp);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-size: 11px;
    }
    /* Desktop restore: original group header padding */
    @media (min-width: 768px) {
        .grouphdr td {
            padding-top: 14px;
        }
    }
</style>
