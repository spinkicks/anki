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
    /* Mobile-first base: full width, compact padding */
    .memory {
        width: 100%;
        padding: 12px;
        font-family: system-ui, sans-serif;
    }
    /* Desktop restore: constrained max-width, original padding */
    @media (min-width: 768px) {
        .memory {
            max-width: 820px;
            margin: 0 auto;
            padding: 16px;
        }
    }
    .titlebar {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .explain {
        color: var(--fg-subtle, #666);
    }
    .coverage {
        font-weight: 600;
    }
    .updated {
        float: right;
        font-weight: 400;
        color: var(--fg-subtle, #888);
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
        color: var(--fg-subtle, #888);
        border-bottom: 1px solid var(--border, #ddd);
        padding: 6px 4px;
    }
    .scaffolding-note {
        font-size: 0.85em;
        font-weight: 400;
        color: var(--fg-subtle, #aaa);
        font-style: italic;
    }

    /* Mobile: td padding (base) */
    :global(.memory td) {
        padding: 6px 4px;
        border-bottom: 1px solid var(--border, #f0f0f0);
    }

    /* Mobile: tbody rows as stacked cards */
    :global(.memory tbody tr:not(.grouphdr)) {
        display: block;
        border-bottom: 2px solid var(--border, #ddd);
        margin-bottom: 12px;
        padding: 12px;
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
        }
        :global(.memory tbody tr:not(.grouphdr) td) {
            display: table-cell;
            padding: 6px 4px;
            border-bottom: 1px solid var(--border, #f0f0f0);
        }
    }

    /* Mobile: compact group header */
    .grouphdr td {
        font-weight: 700;
        padding-top: 8px;
        color: var(--fg, #444);
    }
    /* Desktop restore: original group header padding */
    @media (min-width: 768px) {
        .grouphdr td {
            padding-top: 14px;
        }
    }
</style>
