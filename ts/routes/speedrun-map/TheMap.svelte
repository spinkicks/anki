<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

The Map — interactive prerequisite graph. Tap a topic to see its "blast radius":
every downstream topic whose readiness its weakness caps. Colors encode real
mastery; abstaining topics stay grey and show no fabricated number.
-->
<script lang="ts">
    import { onMount } from "svelte";
    import { loadMap } from "./data";
    import { blastRadius, masteryColor, type MapNode, type MapView } from "./graph";

    let view: MapView | null = null;
    let loading = true;
    let error = "";
    let selected: string | null = null;

    onMount(async () => {
        try {
            view = await loadMap("gre_math");
            if (!view) error = "No exam profile found — import the Speedrun deck first.";
        } catch (e) {
            error = `Could not load the map: ${e}`;
        } finally {
            loading = false;
        }
    });

    $: edges = view?.edges ?? [];
    $: blast = selected ? blastRadius(selected, edges) : new Set<string>();
    $: selectedNode = view?.nodes.find((n) => n.id === selected) ?? null;
    // An edge is "hot" when it carries the selected weakness downstream.
    $: hotEdge = (from: string, to: string): boolean =>
        selected !== null && (from === selected || blast.has(from)) && blast.has(to);
    $: dimmed = (id: string): boolean =>
        selected !== null && id !== selected && !blast.has(id);

    function pick(id: string): void {
        selected = selected === id ? null : id;
    }
    function nodeCenter(id: string): MapNode | undefined {
        return view?.nodes.find((n) => n.id === id);
    }
    function recallLabel(n: MapNode): string {
        if (n.isContainer) return "group";
        if (n.abstained) return "—";
        return `${Math.round(n.avgRecall * 100)}%`;
    }
</script>

<div class="map">
    <header>
        <div class="brand">
            <span class="wordmark">SPEED<span class="pace">RUN</span></span>
            <span class="crumb">· THE MAP</span>
        </div>
        <a class="home-link" href="/speedrun-home">‹ HOME</a>
    </header>

    <p class="lede">
        The GRE Math prerequisite graph. Calculus is the root that unlocks most of the
        exam. <strong>Tap a topic</strong> to light up its <em>blast radius</em> — every
        downstream topic its weakness caps.
    </p>

    {#if loading}
        <div class="state">Loading the map…</div>
    {:else if error}
        <div class="state err">{error}</div>
    {:else if view}
        <div class="canvas-wrap">
            <div class="canvas" style={`width:${view.width}px;height:${view.height}px`}>
                <svg class="edges" width={view.width} height={view.height} aria-hidden="true">
                    <defs>
                        <marker
                            id="arrow"
                            viewBox="0 0 10 10"
                            refX="9"
                            refY="5"
                            markerWidth="6"
                            markerHeight="6"
                            orient="auto-start-reverse"
                        >
                            <path d="M0,0 L10,5 L0,10 z" fill="#3a424d" />
                        </marker>
                        <marker
                            id="arrow-hot"
                            viewBox="0 0 10 10"
                            refX="9"
                            refY="5"
                            markerWidth="6"
                            markerHeight="6"
                            orient="auto-start-reverse"
                        >
                            <path d="M0,0 L10,5 L0,10 z" fill="var(--pace)" />
                        </marker>
                    </defs>
                    {#each edges as e (e.from + ">" + e.to)}
                        {@const a = nodeCenter(e.from)}
                        {@const b = nodeCenter(e.to)}
                        {#if a && b}
                            <line
                                x1={a.x}
                                y1={a.y}
                                x2={b.x}
                                y2={b.y}
                                class:hot={hotEdge(e.from, e.to)}
                                class:faded={selected !== null && !hotEdge(e.from, e.to)}
                                marker-end={hotEdge(e.from, e.to)
                                    ? "url(#arrow-hot)"
                                    : "url(#arrow)"}
                            />
                        {/if}
                    {/each}
                </svg>

                {#each view.nodes as n (n.id)}
                    <button
                        class="node"
                        class:container={n.isContainer}
                        class:selected={n.id === selected}
                        class:blast={blast.has(n.id)}
                        class:dim={dimmed(n.id)}
                        style={`left:${n.x}px;top:${n.y}px;--fill:${masteryColor(n)}`}
                        on:click={() => pick(n.id)}
                        title={n.name}
                    >
                        <span class="nm">{n.name}</span>
                        {#if !n.isContainer}
                            <span class="mm">{recallLabel(n)}</span>
                        {/if}
                    </button>
                {/each}
            </div>
        </div>

        <div class="legend">
            <span class="key"><i class="sw weak"></i> weak</span>
            <span class="key"><i class="sw mid"></i> partial</span>
            <span class="key"><i class="sw strong"></i> strong</span>
            <span class="key"><i class="sw abs"></i> abstains (—)</span>
            <span class="key"><i class="sw sel"></i> selected → blast radius</span>
        </div>

        {#if selectedNode}
            <aside class="detail">
                <div class="dhead">
                    <strong>{selectedNode.name}</strong>
                    <button class="clear" on:click={() => (selected = null)}>✕ clear</button>
                </div>
                <dl>
                    <div><dt>Recall</dt><dd>{recallLabel(selectedNode)}</dd></div>
                    <div>
                        <dt>Exam weight</dt>
                        <dd>{selectedNode.isContainer ? "—" : `${Math.round(selectedNode.weight * 100)}%`}</dd>
                    </div>
                    <div><dt>Caps (downstream)</dt><dd>{blast.size} topic{blast.size === 1 ? "" : "s"}</dd></div>
                    {#if !selectedNode.isContainer && selectedNode.abstained}
                        <div class="unlock">
                            <dt>Status</dt>
                            <dd>Insufficient data — answer {selectedNode.unlockN} more to unlock a recall estimate.</dd>
                        </div>
                    {/if}
                </dl>
            </aside>
        {/if}
    {/if}
</div>

<style>
    .map {
        --ink: #0b0e12;
        --panel: #12161c;
        --line: #232a33;
        --fg: #e6eaef;
        --muted: #7c8794;
        --pace: #f4f7fa;
        --disp: "Manrope", "Segoe UI", system-ui, sans-serif;
        background: var(--ink);
        color: var(--fg);
        font-family: var(--disp);
        min-height: 100vh;
        padding: 16px;
        box-sizing: border-box;
    }
    @media (min-width: 768px) {
        .map {
            max-width: 1040px;
            margin: 0 auto;
            border-inline: 1px solid var(--line);
            padding: 24px;
        }
    }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    .wordmark {
        font-weight: 800;
        letter-spacing: 0.02em;
        font-size: 20px;
    }
    .pace {
        color: var(--pace);
    }
    .crumb {
        color: var(--muted);
        font-weight: 800;
        font-size: 13px;
        margin-left: 6px;
    }
    .home-link {
        color: var(--muted);
        text-decoration: none;
        font-weight: 800;
        font-size: 13px;
        min-height: 44px;
        display: inline-flex;
        align-items: center;
    }
    .home-link:hover {
        color: var(--fg);
    }
    .lede {
        color: var(--muted);
        font-size: 14px;
        line-height: 1.5;
        max-width: 640px;
    }
    .lede strong {
        color: var(--fg);
    }
    .state {
        padding: 40px 0;
        color: var(--muted);
    }
    .state.err {
        color: #c2603f;
    }
    /* Graph is wider than a phone — scroll horizontally on small screens. */
    .canvas-wrap {
        overflow-x: auto;
        overflow-y: hidden;
        border: 1px solid var(--line);
        background: radial-gradient(circle at 30% 20%, #10151b, var(--ink));
        border-radius: 8px;
        padding: 8px;
    }
    .canvas {
        position: relative;
    }
    .edges {
        position: absolute;
        inset: 0;
        pointer-events: none;
    }
    .edges line {
        stroke: #2b333d;
        stroke-width: 1.5;
    }
    .edges line.hot {
        stroke: var(--pace);
        stroke-width: 2.5;
    }
    .edges line.faded {
        stroke: #1b212a;
    }
    .node {
        position: absolute;
        transform: translate(-50%, -50%);
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        min-width: 128px;
        max-width: 150px;
        min-height: 44px;
        padding: 8px 10px;
        background: var(--panel);
        color: var(--fg);
        border: 1px solid var(--line);
        border-left: 4px solid var(--fill);
        border-radius: 6px;
        cursor: pointer;
        font-family: var(--disp);
        text-align: left;
        transition:
            opacity 0.15s,
            border-color 0.15s,
            box-shadow 0.15s;
    }
    .node.container {
        background: #0e1319;
        border-left-color: var(--muted);
    }
    .node .nm {
        font-size: 12px;
        font-weight: 600;
        line-height: 1.15;
    }
    .node .mm {
        font-size: 12px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        color: var(--fill);
    }
    .node.selected {
        border-color: var(--pace);
        box-shadow: 0 0 0 2px var(--pace);
    }
    .node.blast {
        border-color: var(--pace);
    }
    .node.dim {
        opacity: 0.32;
    }
    .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 12px;
        font-size: 12px;
        color: var(--muted);
    }
    .key {
        display: inline-flex;
        align-items: center;
        gap: 5px;
    }
    .sw {
        width: 12px;
        height: 12px;
        border-radius: 3px;
        display: inline-block;
    }
    .sw.weak {
        background: #b4573f;
    }
    .sw.mid {
        background: #c9a24a;
    }
    .sw.strong {
        background: #5aa96a;
    }
    .sw.abs {
        background: #333b45;
    }
    .sw.sel {
        background: var(--pace);
    }
    .detail {
        margin-top: 16px;
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px 16px;
    }
    .dhead {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 8px;
    }
    .dhead strong {
        font-size: 15px;
    }
    .clear {
        background: none;
        border: 1px solid var(--line);
        color: var(--muted);
        border-radius: 6px;
        padding: 6px 10px;
        min-height: 36px;
        cursor: pointer;
        font-family: var(--disp);
        font-size: 12px;
    }
    .clear:hover {
        color: var(--fg);
        border-color: var(--muted);
    }
    dl {
        margin: 0;
        display: flex;
        flex-wrap: wrap;
        gap: 8px 24px;
    }
    dl > div {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    dt {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--muted);
    }
    dd {
        margin: 0;
        font-size: 14px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
    }
    .unlock dd {
        font-weight: 500;
        color: var(--muted);
    }
</style>
