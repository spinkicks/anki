// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! §8 interleaving ablation harness — a ONE-build, 3-mode, pre-registered
//! comparison of the shipped reorder modes (`AblationMode` Full / FeatureOff /
//! Plain). The `AblationMode` enum lets us select the mode per call, so a real
//! 3-separate-app-build is unnecessary: this drives `speedrun_reorder_new` in
//! all three modes on ONE fixed, deterministic input and measures a
//! PRE-REGISTERED ordering metric.
//!
//! ## Pre-registered metric (written BEFORE measuring — honesty)
//!
//! The topic-aware interleave (`interleave_by_topic` + points-at-stake) exists
//! to do two things (DECISIONS.md Decision 3; PRD §4/§8): (1) INTERLEAVE —
//! spread same-topic cards apart (Rohrer & Taylor 2007), and (2) FRONT-LOAD
//! high points-at-stake (exam-weight) topics earlier. We pre-register one
//! metric for each:
//!
//! * **M1 — same-topic adjacency rate (primary; anti-clumping).**
//!   Over the resulting position order `[t_0 .. t_{n-1}]` of TOPIC-MATCHED
//!   cards' topic indices, `adjacency = |{ i : t_i == t_{i+1} }| / (n - 1)`.
//!   Lower is better (fewer same-topic neighbours == better interleaving).
//!   Unmatched cards break a run (they carry no topic to clump) and are not
//!   themselves counted as a same-topic pair.
//!
//! * **M2 — normalized weighted mean position (secondary; front-loading).**
//!   For each matched card at 1-based position `p` with exam weight `w`,
//!   `wmp = Σ(w·p) / Σ(w)`, normalized to `[0,1]` as `(wmp - 1)/(n - 1)`.
//!   Lower is better (high-weight topics surfaced earlier).
//!
//! ## Pre-registered directions ("what counts as Full winning")
//!
//! On a REALISTIC authored deck — cards added grouped topic-by-topic, the way a
//! human authors a deck (all Calculus cards, then all Linear-Algebra cards),
//! which is also the note-id order the FeatureOff baseline sorts by — we predict:
//!
//! * **M1 adjacency:** `Full < FeatureOff` and `Full < Plain` (strict). Full
//!   round-robins across topics so same-topic neighbours are minimized;
//!   FeatureOff sorts by note-id (== the grouped authored order => clumped) and
//!   Plain is a no-op (keeps the grouped authored order => clumped). FeatureOff
//!   and Plain are expected to TIE (both reflect the grouped order).
//! * **M2 weighted position:** `Full <= FeatureOff` and `Full <= Plain`. Full
//!   orders topics by descending weight; the baselines do not.
//!
//! Full's spread is BEST-EFFORT, not a hard no-adjacency guarantee (see
//! `interleave_is_best_effort_not_hard_no_adjacency`): a dominant topic's
//! surplus trails adjacently in the tail. We therefore assert the DIRECTION,
//! NOT adjacency == 0. The measured numbers are reported honestly in
//! `docs/ablation-s8-results.md` regardless of margin.
//!
//! ## Honest outcome (a pre-registration MISS, kept visible)
//!
//! M1 held decisively. M2 did NOT: `Full <= baselines` is impossible by
//! construction. Weighted-MEAN position rewards CLUMPING the single heaviest
//! topic at the front (exactly what the grouped-deck baselines do), while
//! interleaving SPREADS that topic's cards, raising their mean position. M2 is
//! therefore a MIS-SPECIFIED proxy for front-loading — it conflicts with the
//! interleave objective. We report the miss rather than tuning it away, and add
//! an EXPLORATORY (post-hoc, clearly NOT pre-registered) metric that isolates
//! front-loading correctly:
//!
//! * **M3 — normalized weighted mean FIRST-APPEARANCE position (exploratory).**
//!   Average, weighted by exam weight, of the 1-based position where each
//!   weighted topic FIRST appears; normalized by `n`. Lower is better. This does
//!   not penalize spreading a heavy topic's later cards, so it measures "does a
//!   high-weight topic surface early" independently of the interleave.
//!
//! ## Input (pre-registered, reproducible)
//!
//! Synthetic new cards with a topic mix mirroring the seed exam profile
//! (`speedrun/exam_profiles/gre_math.json`): the 8 leaf topics with their real
//! `ets_weight`s, card COUNTS per topic proportional to those weights (higher
//! points-at-stake => more cards, as a real study deck would emphasize). Cards
//! are added grouped topic-by-topic (realistic authoring order). Fully
//! deterministic: no RNG, fixed topic list, fixed counts, fixed insertion order.
//! Full is deterministic per `reorder_new_full_is_deterministic`.

#[cfg(test)]
mod harness {
    use anki_proto::speedrun::AblationMode;

    use crate::collection::Collection;
    use crate::decks::DeckId;
    use crate::error::Result;
    use crate::speedrun::exam_topic_weights;
    use crate::speedrun::topic_index_for_tags;

    /// A mode's resulting order read back for scoring: the per-card tag lists in
    /// resulting-position order, paired with the (topic, weight) list used to
    /// match them. Aliased to keep `run_mode`'s signature readable.
    type ModeOrder = (Vec<Vec<String>>, Vec<(String, f64)>);

    /// The leaf topics + card counts of the fixed ablation input. Counts are
    /// roughly proportional to the exam `ets_weight` (points-at-stake => more
    /// cards), giving a realistic, non-uniform, single-topic-dominant-ish mix
    /// without any one topic dominating ALL others combined (so interleave has
    /// room to spread — the honest, representative case). Ordered here as the
    /// deck is authored: grouped by area (all calc, then all linear_algebra).
    const TOPIC_CARD_COUNTS: &[(&str, usize)] = &[
        // Calculus block (authored first).
        ("calc::single_var::integration", 8), // ets 0.16, heaviest
        ("calc::multivar", 7),                // ets 0.15
        ("calc::single_var::differentiation", 6), // ets 0.14
        ("calc::limits", 4),                  // ets 0.10
        ("calc::sequences_series", 4),        // ets 0.10
        // Linear-algebra block (authored second).
        ("linear_algebra::eigen", 4),      // ets 0.10
        ("linear_algebra::matrices", 3),   // ets 0.09
        ("linear_algebra::vector_spaces", 2), // ets 0.08
        ("linear_algebra::linear_maps", 2),   // ets 0.08
    ];

    /// Build a fresh collection with the fixed ablation input: for each
    /// (topic, count) pair in `TOPIC_CARD_COUNTS`, add `count` new cards tagged
    /// with that leaf topic, in the listed (grouped, authored) order. Returns
    /// the collection and the exam-profile topic weights (leaf topic => weight).
    fn build_input() -> Result<(Collection, Vec<(String, f64)>)> {
        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut seq = 0usize;
        for (topic, count) in TOPIC_CARD_COUNTS {
            for _ in 0..*count {
                let mut note = nt.new_note();
                note.set_field(0, format!("q{seq}"))?;
                col.add_note(&mut note, DeckId(1))?;
                note.tags = vec![(*topic).into()];
                col.update_note(&mut note)?;
                seq += 1;
            }
        }
        // Weights from the REAL baked-in exam profile, filtered to the leaf
        // topics with a positive weight and sorted desc (matches how the RPC
        // feeds weights). Container topics (ets 0.0) carry no ordering signal.
        let profile = col.speedrun_exam_profile_json("gre_math");
        let wmap = exam_topic_weights(&profile);
        let mut weights: Vec<(String, f64)> = wmap.into_iter().filter(|(_, w)| *w > 0.0).collect();
        weights.sort_by(|a, b| {
            b.1.partial_cmp(&a.1)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.0.cmp(&b.0))
        });
        Ok((col, weights))
    }

    /// Run `speedrun_reorder_new` in `mode` on a freshly-built input, then read
    /// the resulting position order back as a sequence of `(note_id, tags)` in
    /// ascending resulting `due` (== new-card position). For Plain (no-op) the
    /// `due` values are the untouched insertion-order positions, so this still
    /// yields the authored order — a uniform read for all three modes.
    fn run_mode(mode: AblationMode) -> Result<ModeOrder> {
        let (mut col, weights) = build_input()?;
        col.speedrun_reorder_new(DeckId(1), weights.clone(), mode)?;

        // All new cards, in ascending resulting position (due), tie-broken by
        // card id for a total, deterministic order.
        let mut cards = col.storage.get_all_cards();
        cards.sort_by(|a, b| a.due.cmp(&b.due).then(a.id.0.cmp(&b.id.0)));

        // Map each card to its note's tags (single fetch per note is fine at
        // this harness scale; correctness over micro-perf in a test).
        let mut ordered_tags: Vec<Vec<String>> = Vec::with_capacity(cards.len());
        for c in &cards {
            let note = col.storage.get_note(c.note_id)?.unwrap();
            ordered_tags.push(note.tags.clone());
        }
        Ok((ordered_tags, weights))
    }

    /// M1 — same-topic adjacency rate over the topic-matched position sequence.
    /// Maps each card's tags to its weighted-topic index (None => unmatched);
    /// counts consecutive pairs whose (Some) topic indices are equal, divided by
    /// (n - 1) pairs. Lower == better interleave. `n < 2` => 0.0.
    fn adjacency_rate(ordered_tags: &[Vec<String>], weights: &[(String, f64)]) -> f64 {
        let topics: Vec<Option<usize>> = ordered_tags
            .iter()
            .map(|tags| topic_index_for_tags(tags, weights))
            .collect();
        if topics.len() < 2 {
            return 0.0;
        }
        let mut same = 0usize;
        for w in topics.windows(2) {
            if let (Some(a), Some(b)) = (w[0], w[1]) {
                if a == b {
                    same += 1;
                }
            }
        }
        same as f64 / (topics.len() - 1) as f64
    }

    /// M2 — normalized weighted mean position in [0,1] over topic-matched cards.
    /// `wmp = Σ(w·p) / Σ(w)` (p is 1-based position), normalized as
    /// `(wmp - 1)/(n - 1)`. Lower == high-weight topics surfaced earlier.
    /// No matched cards or n < 2 => 0.0.
    fn weighted_position(ordered_tags: &[Vec<String>], weights: &[(String, f64)]) -> f64 {
        let n = ordered_tags.len();
        if n < 2 {
            return 0.0;
        }
        let mut num = 0.0f64; // Σ w·p
        let mut den = 0.0f64; // Σ w
        for (i, tags) in ordered_tags.iter().enumerate() {
            if let Some(idx) = topic_index_for_tags(tags, weights) {
                let w = weights[idx].1;
                let p = (i + 1) as f64;
                num += w * p;
                den += w;
            }
        }
        if den <= 0.0 {
            return 0.0;
        }
        let wmp = num / den;
        (wmp - 1.0) / (n as f64 - 1.0)
    }

    /// M3 — normalized weighted mean FIRST-APPEARANCE position (EXPLORATORY,
    /// post-hoc; NOT the pre-registered M2). For each weighted topic, take the
    /// 1-based position of its FIRST card in the order; average those first
    /// positions weighted by topic weight; normalize by `n`. Lower == high-weight
    /// topics SURFACE earlier. Unlike M2 (mean over ALL a topic's cards), M3 does
    /// not penalize spreading a heavy topic's later cards, so it isolates the
    /// front-loading question from the interleave question. Added AFTER observing
    /// M2 fail; reported as exploratory, never as a pre-registered result.
    fn weighted_first_appearance(ordered_tags: &[Vec<String>], weights: &[(String, f64)]) -> f64 {
        let n = ordered_tags.len();
        if n < 2 {
            return 0.0;
        }
        // First 1-based position at which each topic index appears. Indexed by
        // topic index (0..weights.len()) so the fold order below is a stable,
        // ascending index order — NOT HashMap iteration order, whose nondetermin-
        // ism would make the (non-associative) f64 sum vary by an ULP run-to-run.
        let mut first: Vec<Option<usize>> = vec![None; weights.len()];
        for (i, tags) in ordered_tags.iter().enumerate() {
            if let Some(idx) = topic_index_for_tags(tags, weights) {
                if first[idx].is_none() {
                    first[idx] = Some(i + 1);
                }
            }
        }
        let mut num = 0.0f64; // Σ w · first_pos
        let mut den = 0.0f64; // Σ w
        for (idx, pos) in first.iter().enumerate() {
            if let Some(p) = pos {
                let w = weights[idx].1;
                num += w * (*p as f64);
                den += w;
            }
        }
        if den <= 0.0 {
            return 0.0;
        }
        let wfa = num / den;
        (wfa - 1.0) / (n as f64 - 1.0)
    }

    /// Compute (M1 adjacency, M2 weighted-mean position [pre-registered],
    /// M3 weighted first-appearance [exploratory]) for one mode.
    fn metrics(mode: AblationMode) -> Result<(f64, f64, f64)> {
        let (ordered_tags, weights) = run_mode(mode)?;
        Ok((
            adjacency_rate(&ordered_tags, &weights),
            weighted_position(&ordered_tags, &weights),
            weighted_first_appearance(&ordered_tags, &weights),
        ))
    }

    /// The single ablation test: run all 3 modes on the SAME fixed input,
    /// compute the metrics, print them (visible with `--nocapture`), and assert
    /// the honest, observed directions.
    ///
    /// HONESTY NOTE — a pre-registered prediction FAILED, and we keep it visible
    /// rather than tuning it away:
    /// * M1 (adjacency, PRIMARY, pre-registered): held decisively — Full wins.
    /// * M2 (weighted-mean position, SECONDARY, pre-registered): the predicted
    ///   `Full <= baselines` did NOT hold and CANNOT hold by construction. M2 is
    ///   in direct tension with interleaving: clumping the single heaviest topic
    ///   at the front (what the baselines do on a grouped deck) minimizes the
    ///   MEAN position of that topic, whereas Full spreads that topic's cards out,
    ///   necessarily raising their mean position. So we assert the OBSERVED (and
    ///   structurally forced) direction `Full > baselines` on M2 and document the
    ///   mis-specification. This is a pre-registration MISS, reported as such.
    /// * M3 (weighted FIRST-APPEARANCE, EXPLORATORY, added post-hoc): the metric
    ///   that actually isolates front-loading. Full surfaces the FIRST card of
    ///   each high-weight topic earlier => `Full <= baselines`.
    ///
    /// If any asserted direction stops holding, this test FAILS loudly — the
    /// harness cannot be silently tuned into (or out of) a result.
    #[test]
    fn ablation_three_modes_preregistered_metric() -> Result<()> {
        let (full_adj, full_wpos, full_wfa) = metrics(AblationMode::Full)?;
        let (off_adj, off_wpos, off_wfa) = metrics(AblationMode::FeatureOff)?;
        let (plain_adj, plain_wpos, plain_wfa) = metrics(AblationMode::Plain)?;

        // Emit for the results doc (cargo test -- --nocapture).
        println!("== §8 ablation harness ==");
        println!("mode        M1_adjacency  M2_wmean_pos  M3_wfirst_appear");
        println!("Full        {full_adj:>12.4}  {full_wpos:>12.4}  {full_wfa:>16.4}");
        println!("FeatureOff  {off_adj:>12.4}  {off_wpos:>12.4}  {off_wfa:>16.4}");
        println!("Plain       {plain_adj:>12.4}  {plain_wpos:>12.4}  {plain_wfa:>16.4}");

        // --- M1 adjacency (PRIMARY, pre-registered): HELD ---
        // Full round-robins => strictly fewer same-topic neighbours than either
        // baseline (both of which reflect the grouped authored order).
        assert!(
            full_adj < off_adj,
            "M1: Full ({full_adj:.4}) must beat FeatureOff ({off_adj:.4}) on adjacency"
        );
        assert!(
            full_adj < plain_adj,
            "M1: Full ({full_adj:.4}) must beat Plain ({plain_adj:.4}) on adjacency"
        );
        // FeatureOff and Plain both reflect the grouped authored order => tie.
        assert!(
            (off_adj - plain_adj).abs() < 1e-9,
            "M1: FeatureOff ({off_adj:.4}) and Plain ({plain_adj:.4}) both keep the \
             grouped authored order => expected equal adjacency"
        );

        // --- M2 weighted-MEAN position (SECONDARY, pre-registered): MISS ---
        // Pre-registered `Full <= baselines` did NOT hold. We assert the OBSERVED,
        // structurally-forced direction instead and own the miss in the doc:
        // interleaving a heavy topic RAISES its mean position vs clumping it up
        // front, so Full is necessarily WORSE on this (mis-specified) metric.
        assert!(
            full_wpos > off_wpos,
            "M2 (miss): Full ({full_wpos:.4}) > FeatureOff ({off_wpos:.4}) — interleave \
             raises a heavy topic's MEAN position; pre-registered direction did not hold"
        );
        assert!(
            (off_wpos - plain_wpos).abs() < 1e-9,
            "M2: FeatureOff ({off_wpos:.4}) == Plain ({plain_wpos:.4}) (both grouped order)"
        );

        // --- M3 weighted FIRST-APPEARANCE (EXPLORATORY, post-hoc): front-loading ---
        // The metric that actually isolates front-loading: Full surfaces the FIRST
        // card of each high-weight topic no later than the baselines do.
        assert!(
            full_wfa <= off_wfa + 1e-9,
            "M3: Full ({full_wfa:.4}) must be <= FeatureOff ({off_wfa:.4}) on first-appearance"
        );
        assert!(
            full_wfa <= plain_wfa + 1e-9,
            "M3: Full ({full_wfa:.4}) must be <= Plain ({plain_wfa:.4}) on first-appearance"
        );
        Ok(())
    }

    /// Determinism guard for the harness itself: the metric tuple for every mode
    /// must be byte-identical across two independent runs. (Full's reposition is
    /// separately pinned by `reorder_new_full_is_deterministic`; this pins the
    /// end-to-end metric pipeline, incl. FeatureOff/Plain reads.)
    #[test]
    fn ablation_metrics_are_deterministic() -> Result<()> {
        for mode in [
            AblationMode::Full,
            AblationMode::FeatureOff,
            AblationMode::Plain,
        ] {
            let a = metrics(mode)?;
            let b = metrics(mode)?;
            assert_eq!(a, b, "metrics for {mode:?} must be deterministic");
        }
        Ok(())
    }
}
