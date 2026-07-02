<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    // Honest run status (spec: "keep honest/derived, not fake"): the mockup's
    // "SESSION 04 · PB PACE" is placeholder. We have no session counter and no
    // timing data, so we derive from real review counts instead:
    //   timedReviewsTotal === 0  -> "NO RUN YET" (muted, no amber dot)
    //   else                     -> amber-dot + "RUN ACTIVE"
    //                               + "{n} REVIEWS LOGGED"
    // We deliberately do NOT show "PB PACE" — no timing data exists, so a
    // personal-best pace would be fabricated.
    export let timedReviewsTotal: number;

    $: active = timedReviewsTotal > 0;
</script>

<header>
    <div>
        <div class="wordmark">
            <span class="s">SPEED</span>
            <span class="k">RUN</span>
        </div>
        <div class="subtitle">GRE Mathematics · Subject Test</div>
    </div>
    <div class="status">
        {#if active}
            <span class="dot"></span>
            <span class="live">RUN ACTIVE</span>
            <br />
            {timedReviewsTotal} REVIEWS LOGGED
        {:else}
            NO RUN YET
            <br />
            BEGIN A RUN TO SET A PACE
        {/if}
    </div>
</header>

<style>
    /* Mobile-first base: stacked column */
    header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        flex-direction: column;
        gap: 12px;
        padding: 16px;
        border-bottom: 1px solid var(--line);
    }
    /* Desktop restore: horizontal row, original padding */
    @media (min-width: 768px) {
        header {
            flex-direction: row;
            gap: 0;
            padding: 22px 28px 18px;
        }
    }
    /* Wordmark: Manrope ExtraBold, tight tracking, subtle two-tone light split
       — SPEED in --fg (#e6eaef), RUN a touch brighter in --pace (#f4f7fa).
       Hierarchy from weight+brightness, not a colored accent (identity spec §3). */
    .wordmark {
        /* inline-flex collapses the whitespace text node the formatter inserts
           between the two spans, so SPEED+RUN reads as one tight word. */
        display: inline-flex;
        font-family: var(--disp);
        font-weight: 800;
        font-size: clamp(18px, 5vw, 22px);
        letter-spacing: 0.04em;
    }
    @media (min-width: 768px) {
        .wordmark {
            font-size: 22px;
        }
    }
    .wordmark .s {
        color: var(--fg);
    }
    .wordmark .k {
        color: var(--pace);
    }
    .subtitle {
        font-family: var(--disp);
        font-size: 11px;
        letter-spacing: 0.28em;
        color: var(--muted);
        margin-top: 6px;
        text-transform: uppercase;
    }
    /* Mobile-first: status left-aligned; desktop restore: right-aligned */
    .status {
        font-family: var(--disp);
        font-variant-numeric: tabular-nums;
        font-size: 11px;
        letter-spacing: 0.18em;
        color: var(--muted);
        text-align: left;
        text-transform: uppercase;
    }
    @media (min-width: 768px) {
        .status {
            text-align: right;
        }
    }
    .status .live {
        color: var(--pace);
    }
    .status .dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        background: var(--pace);
        margin-right: 6px;
        vertical-align: middle;
    }
</style>
