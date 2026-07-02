// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pub(crate) mod exam_profile;
pub(crate) mod service;

/// Count how many `required` topic tags are present among the collection's
/// `all_tags`. A required tag `t` is "present" if any collection tag equals `t`
/// or is a hierarchical descendant `t::...` (Anki uses `::` for tag hierarchy).
/// Returns `(covered, total)`.
pub(crate) fn coverage(all_tags: &[String], required: &[String]) -> (u32, u32) {
    let total = required.len() as u32;
    let covered = required
        .iter()
        .filter(|req| {
            let prefix = format!("{req}::");
            all_tags
                .iter()
                .any(|t| t.as_str() == req.as_str() || t.starts_with(&prefix))
        })
        .count() as u32;
    (covered, total)
}

/// Default retrievability at/above which a card counts as "mastered".
pub(crate) const MASTERY_THRESHOLD_DEFAULT: f64 = 0.9;
/// Default minimum graded reviews before a topic reports a (non-abstained)
/// score.
pub(crate) const MIN_REVIEWS_DEFAULT: u32 = 20;
/// z for a 95% two-sided interval.
pub(crate) const WILSON_Z_95: f64 = 1.96;

/// Aggregate per-card retrievabilities into (cards_with_data, mastered_count,
/// avg_recall). `retrievabilities` contains one entry per card that HAS an FSRS
/// memory state. `avg_recall` is 0.0 when the slice is empty.
pub(crate) fn topic_aggregate(retrievabilities: &[f64], threshold: f64) -> (u32, u32, f64) {
    let n = retrievabilities.len() as u32;
    if n == 0 {
        return (0, 0, 0.0);
    }
    let mastered = retrievabilities.iter().filter(|r| **r >= threshold).count() as u32;
    let avg = retrievabilities.iter().sum::<f64>() / n as f64;
    (n, mastered, avg)
}

/// Wilson score interval for a binomial proportion `successes / n` at the given
/// z. Returns (lower, upper) clamped to [0, 1]. `n == 0` => (0.0, 1.0) (total
/// uncertainty), which the caller treats as an abstain signal.
pub(crate) fn wilson_interval(successes: u32, n: u32, z: f64) -> (f64, f64) {
    if n == 0 {
        return (0.0, 1.0);
    }
    let n = n as f64;
    let p = successes as f64 / n;
    let z2 = z * z;
    let denom = 1.0 + z2 / n;
    let center = (p + z2 / (2.0 * n)) / denom;
    let margin = (z / denom) * ((p * (1.0 - p) / n) + z2 / (4.0 * n * n)).sqrt();
    ((center - margin).max(0.0), (center + margin).min(1.0))
}

/// Given new-card note-ids each paired with their topic index (or None if the
/// card matches no weighted topic), and topic indices sorted by descending
/// points-at-stake, return the note-ids in interleaved order: round-robin
/// across topics in priority order, so no two adjacent cards share a topic when
/// multiple topics have remaining cards. Unmatched cards (None) go last, in
/// input order. Input order within a topic is preserved (stable).
pub(crate) fn interleave_by_topic(
    ordered_topic_indices: &[usize],
    note_topic: &[(i64, Option<usize>)],
) -> Vec<i64> {
    use std::collections::VecDeque;
    let mut buckets: std::collections::HashMap<usize, VecDeque<i64>> = Default::default();
    let mut unmatched: Vec<i64> = Vec::new();
    for (nid, topic) in note_topic {
        match topic {
            Some(t) => buckets.entry(*t).or_default().push_back(*nid),
            None => unmatched.push(*nid),
        }
    }
    let mut out = Vec::with_capacity(note_topic.len());
    loop {
        let mut progressed = false;
        for &t in ordered_topic_indices {
            if let Some(q) = buckets.get_mut(&t) {
                if let Some(nid) = q.pop_front() {
                    out.push(nid);
                    progressed = true;
                }
            }
        }
        if !progressed {
            break;
        }
    }
    out.extend(unmatched);
    out
}

/// Match a topic tag set to the index of the highest-priority weighted topic a
/// card belongs to (prefix rule: tag == topic or starts with "topic::").
/// `weighted` is (topic, weight) already sorted by descending weight.
pub(crate) fn topic_index_for_tags(tags: &[String], weighted: &[(String, f64)]) -> Option<usize> {
    for (i, (topic, _)) in weighted.iter().enumerate() {
        let prefix = format!("{topic}::");
        if tags.iter().any(|t| t == topic || t.starts_with(&prefix)) {
            return Some(i);
        }
    }
    None
}

/// Synced-config key holding the read-time review-interleave feature state.
/// Absent => feature OFF (Anki's default SQL review order, untouched Anki).
pub(crate) const REVIEW_INTERLEAVE_CONFIG_KEY: &str = "speedrun:review_interleave";

/// Feature config read from the synced collection config. `mode` mirrors
/// `AblationMode` (0=Full, 1=FeatureOff, 2=Plain); `weights` are (topic,
/// ets_weight) pairs from the exam profile. Only Full reorders reviews.
#[derive(Debug, Clone, serde::Deserialize)]
pub(crate) struct ReviewInterleaveConfig {
    pub mode: i32,
    #[serde(default)]
    pub weights: Vec<(String, f64)>,
}

/// Pure read-time ordering for the due REVIEW queue. Given review cards as
/// `(card_id, topic_index, retrievability)` and exam-profile `weights`
/// (topic, weight) SORTED BY DESCENDING WEIGHT, return the card_ids ordered by
/// points-at-stake and interleaved by topic (no two adjacent same-topic when
/// avoidable).
///
/// `points_at_stake = (1 - retrievability) * topic_weight` (weakness × weight).
/// Topics run in descending aggregate points-at-stake; within a topic the weakest
/// (highest points) card comes first; ties broken by `card_id` for determinism.
/// Cards with no weighted topic go last (weakest-first, then card_id).
pub(crate) fn interleave_reviews_by_weakness(
    cards: &[(i64, Option<usize>, f64)],
    weights: &[(String, f64)],
) -> Vec<i64> {
    use std::collections::HashMap;
    let points = |topic: Option<usize>, r: f64| -> f64 {
        let w = topic
            .and_then(|i| weights.get(i))
            .map(|(_, w)| *w)
            .unwrap_or(0.0);
        (1.0 - r) * w
    };
    // Aggregate points per topic => topic run order (desc, tie by index).
    let mut agg: HashMap<usize, f64> = HashMap::new();
    for (_, topic, r) in cards {
        if let Some(t) = topic {
            *agg.entry(*t).or_default() += points(Some(*t), *r);
        }
    }
    let mut ordered_topics: Vec<usize> = agg.keys().copied().collect();
    ordered_topics.sort_by(|a, b| {
        agg[b]
            .partial_cmp(&agg[a])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(b))
    });
    // Global points-desc sort (deterministic tie by card_id); because
    // interleave_by_topic preserves input order within a bucket, this yields
    // weakest-first within each topic.
    let mut sorted = cards.to_vec();
    sorted.sort_by(|a, b| {
        points(b.1, b.2)
            .partial_cmp(&points(a.1, a.2))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.0.cmp(&b.0))
    });
    let note_topic: Vec<(i64, Option<usize>)> = sorted.iter().map(|(c, t, _)| (*c, *t)).collect();
    interleave_by_topic(&ordered_topics, &note_topic)
}

#[cfg(test)]
mod test {
    use super::coverage;
    use super::interleave_by_topic;
    use super::interleave_reviews_by_weakness;
    use super::topic_aggregate;
    use super::topic_index_for_tags;
    use super::wilson_interval;
    use super::MASTERY_THRESHOLD_DEFAULT;
    use crate::collection::Collection;
    use crate::decks::DeckId;
    use crate::error::Result;
    use crate::services::SpeedrunService;

    fn strs(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn all_required_present_counts_full() {
        let all = strs(&["calc::integration", "linear_algebra::eigen"]);
        let required = strs(&["calc", "linear_algebra"]);
        assert_eq!(coverage(&all, &required), (2, 2));
    }

    #[test]
    fn partial_coverage_counts_present_only() {
        let all = strs(&["calc::integration"]);
        let required = strs(&["calc", "linear_algebra", "abstract_algebra"]);
        assert_eq!(coverage(&all, &required), (1, 3));
    }

    #[test]
    fn prefix_matches_descendants_but_not_substrings() {
        // "calc" is covered by "calc" or "calc::*", but NOT by "calculus_tricks".
        let all = strs(&["calculus_tricks", "calc::limits"]);
        assert_eq!(coverage(&all, &strs(&["calc"])), (1, 1));
        // Exact, no descendants.
        let all_exact = strs(&["calc"]);
        assert_eq!(coverage(&all_exact, &strs(&["calc"])), (1, 1));
        // Empty required => zero of zero.
        assert_eq!(coverage(&all_exact, &[]), (0, 0));
    }

    #[test]
    fn get_coverage_reads_live_collection_tags() -> Result<()> {
        let mut col = Collection::new();

        // No notes yet => nothing covered, version present.
        let resp = col.get_coverage(anki_proto::speedrun::GetCoverageRequest {
            required_tags: strs(&["calc", "linear_algebra"]),
        })?;
        assert_eq!(resp.total, 2);
        assert_eq!(resp.covered, 0);
        assert_eq!(resp.percent, 0.0);
        assert!(!resp.backend_version.is_empty());

        // Add a note tagged calc::integration.
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, DeckId(1))?;
        note.tags = vec!["calc::integration".into()];
        col.update_note(&mut note)?;

        let resp = col.get_coverage(anki_proto::speedrun::GetCoverageRequest {
            required_tags: strs(&["calc", "linear_algebra"]),
        })?;
        assert_eq!(resp.covered, 1);
        assert_eq!(resp.total, 2);
        assert!((resp.percent - 50.0).abs() < 1e-9);
        Ok(())
    }

    #[test]
    fn wilson_bounds_are_inside_unit_interval_and_ordered() {
        let (lo, hi) = wilson_interval(3, 10, 1.96);
        assert!(lo >= 0.0 && hi <= 1.0);
        assert!(lo < hi);
        // Known value: 3/10 Wilson 95% ~ (0.108, 0.603).
        assert!((lo - 0.1078).abs() < 1e-3, "lo={lo}");
        assert!((hi - 0.6032).abs() < 1e-3, "hi={hi}");
    }

    #[test]
    fn wilson_zero_n_is_full_uncertainty() {
        assert_eq!(wilson_interval(0, 0, 1.96), (0.0, 1.0));
    }

    #[test]
    fn topic_aggregate_counts_mastered_and_averages() {
        // retrievabilities for 4 cards; threshold 0.9 => 2 mastered.
        let rs = vec![0.95_f64, 0.91, 0.5, 0.2];
        let (n, mastered, avg) = topic_aggregate(&rs, 0.9);
        assert_eq!(n, 4);
        assert_eq!(mastered, 2);
        assert!((avg - 0.64).abs() < 1e-9);
    }

    #[test]
    fn topic_aggregate_empty_is_zero() {
        let (n, mastered, avg) = topic_aggregate(&[], MASTERY_THRESHOLD_DEFAULT);
        assert_eq!((n, mastered), (0, 0));
        assert_eq!(avg, 0.0);
    }

    #[test]
    fn topic_mastery_abstains_without_enough_reviews() -> Result<()> {
        let mut col = Collection::new();

        // Add a note tagged calc::limits but never reviewed => no memory state.
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, DeckId(1))?;
        note.tags = vec!["calc::limits".into()];
        col.update_note(&mut note)?;

        let resp = col.get_topic_mastery(anki_proto::speedrun::GetTopicMasteryRequest {
            topics: strs(&["calc::limits", "linear_algebra::eigen"]),
            mastery_threshold: 0.0, // => default 0.9
            min_reviews: 0,         // => default 20
        })?;

        assert_eq!(resp.topics.len(), 2);
        let limits = &resp.topics[0];
        assert_eq!(limits.topic, "calc::limits");
        assert_eq!(limits.cards_with_data, 0); // reviewed 0 times => no FSRS state
        assert_eq!(limits.graded_reviews, 0);
        assert!(limits.abstained); // below min_reviews
                                   // Full-uncertainty Wilson when no data.
        assert_eq!((limits.mastered_lower, limits.mastered_upper), (0.0, 1.0));
        assert!(!resp.backend_version.is_empty());
        Ok(())
    }

    #[test]
    fn topic_mastery_scores_with_reviews_and_memory_state() -> Result<()> {
        // Characterization guard for the batched get_topic_mastery: a topic with
        // memory-state-bearing cards + enough graded reviews must report real
        // counts (not abstain). Must hold identically before/after the N+1 batch
        // refactor (values are what matter; the batch is a perf change).
        use crate::card::FsrsMemoryState;
        use crate::revlog::RevlogEntry;
        use crate::revlog::RevlogId;

        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut cids = Vec::new();
        for i in 0..3 {
            let mut note = nt.new_note();
            note.set_field(0, &format!("q{i}"))?;
            col.add_note(&mut note, DeckId(1))?;
            note.tags = vec!["calc::integration".into()];
            col.update_note(&mut note)?;
            let card = col.storage.all_cards_of_note(note.id)?.pop().unwrap();
            cids.push(card.id);
        }
        // Give 2 of the 3 cards a high-retrievability memory state (=> mastered).
        for &cid in &cids[..2] {
            let mut card = col.storage.get_card(cid)?.unwrap();
            card.memory_state = Some(FsrsMemoryState {
                stability: 1000.0,
                difficulty: 5.0,
            });
            col.storage.update_card(&card)?;
        }
        // 3 cards * 8 = 24 graded reviews (button_chosen 3) >= min_reviews 20.
        let mut rid = 1_000i64;
        for &cid in &cids {
            for _ in 0..8 {
                col.storage.add_revlog_entry(
                    &RevlogEntry {
                        id: RevlogId(rid),
                        cid,
                        button_chosen: 3,
                        ..Default::default()
                    },
                    false,
                )?;
                rid += 1;
            }
        }

        let resp = col.get_topic_mastery(anki_proto::speedrun::GetTopicMasteryRequest {
            topics: strs(&["calc::integration"]),
            mastery_threshold: 0.0, // => default 0.9
            min_reviews: 0,         // => default 20
        })?;
        let t = &resp.topics[0];
        // cards_with_data proves the card-scan read memory_state for exactly the
        // 2 memory-state cards; graded_reviews proves the revlog-scan counted all
        // 24 rated rows. These two are the exact observables the N+1 batch touches
        // — they must be identical before and after the refactor.
        assert_eq!(t.cards_with_data, 2, "only the 2 memory-state cards count");
        assert_eq!(t.graded_reviews, 24, "all rated revlog rows counted");
        assert!(!t.abstained, "24 graded reviews >= 20 with data => not abstained");
        assert!(
            (0.0..=1.0).contains(&t.avg_recall),
            "avg_recall in [0,1]: {}",
            t.avg_recall
        );
        assert!(t.mastered_count <= t.cards_with_data);
        Ok(())
    }

    #[test]
    fn interleave_alternates_topics_no_two_adjacent_same() {
        let nt = vec![
            (10, Some(0)),
            (11, Some(0)),
            (12, Some(0)),
            (20, Some(1)),
            (21, Some(1)),
        ];
        let out = interleave_by_topic(&[0, 1], &nt);
        assert_eq!(out, vec![10, 20, 11, 21, 12]);
    }

    #[test]
    fn interleave_unmatched_go_last_in_order() {
        let nt = vec![(1, None), (2, Some(0)), (3, None)];
        assert_eq!(interleave_by_topic(&[0], &nt), vec![2, 1, 3]);
    }

    #[test]
    fn review_interleave_orders_by_points_and_interleaves() {
        // calc (weight .9) has weak cards (low r => high points); linear_algebra
        // (weight .1) has strong cards. calc aggregate dominates => calc leads the
        // round-robin; topics alternate: 1,3,2,4.
        let weights = vec![("calc".into(), 0.9), ("linear_algebra".into(), 0.1)];
        let cards = vec![
            (1, Some(0), 0.2), // calc  points=.72
            (2, Some(0), 0.5), // calc  points=.45
            (3, Some(1), 0.9), // la    points=.01
            (4, Some(1), 0.95), // la   points=.005
        ];
        assert_eq!(
            interleave_reviews_by_weakness(&cards, &weights),
            vec![1, 3, 2, 4]
        );
    }

    #[test]
    fn review_interleave_weakest_first_within_topic() {
        let weights = vec![("calc".into(), 1.0)];
        // single topic: order purely by weakness (points desc): 11(.9),12(.5),10(.1)
        let cards = vec![(10, Some(0), 0.9), (11, Some(0), 0.1), (12, Some(0), 0.5)];
        assert_eq!(
            interleave_reviews_by_weakness(&cards, &weights),
            vec![11, 12, 10]
        );
    }

    #[test]
    fn review_interleave_unmatched_go_last() {
        let weights = vec![("calc".into(), 1.0)];
        let cards = vec![(1, None, 0.2), (2, Some(0), 0.2), (3, None, 0.5)];
        // matched calc card first; unmatched (points 0) last, card_id tiebreak.
        assert_eq!(
            interleave_reviews_by_weakness(&cards, &weights),
            vec![2, 1, 3]
        );
    }

    #[test]
    fn review_interleave_is_deterministic() {
        let weights = vec![("calc".into(), 0.9), ("la".into(), 0.1)];
        let cards = vec![(3, Some(0), 0.3), (1, Some(0), 0.3), (2, Some(1), 0.3)];
        let a = interleave_reviews_by_weakness(&cards, &weights);
        let b = interleave_reviews_by_weakness(&cards, &weights);
        assert_eq!(a, b);
        // equal points in calc => card_id tiebreak (1 before 3); calc agg > la;
        // interleave: calc(1), la(2), calc(3).
        assert_eq!(a, vec![1, 2, 3]);
    }

    #[test]
    fn speedrun_interleave_reviews_config_gated_and_order_only() -> Result<()> {
        use crate::prelude::*;
        use crate::scheduler::queue::DueCard;
        use crate::scheduler::queue::DueCardKind;

        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut ids: Vec<(CardId, NoteId)> = Vec::new();
        for (front, tag) in [("calc1", "calc"), ("calc2", "calc"), ("la1", "linear_algebra")] {
            let mut note = nt.new_note();
            note.set_field(0, front)?;
            col.add_note(&mut note, DeckId(1))?;
            note.tags = vec![tag.into()];
            col.update_note(&mut note)?;
            let card = col.storage.all_cards_of_note(note.id)?.pop().unwrap();
            ids.push((card.id, card.note_id));
        }
        let make_review = |ids: &[(CardId, NoteId)]| -> Vec<DueCard> {
            ids.iter()
                .map(|(cid, nid)| DueCard {
                    id: *cid,
                    note_id: *nid,
                    mtime: TimestampSecs(0),
                    due: 0,
                    current_deck_id: DeckId(1),
                    original_deck_id: DeckId(1),
                    kind: DueCardKind::Review,
                    reps: 1,
                })
                .collect()
        };
        let input: Vec<CardId> = ids.iter().map(|(c, _)| *c).collect();

        // (a) no config => untouched Anki order.
        let mut review = make_review(&ids);
        col.speedrun_interleave_reviews(&mut review)?;
        assert_eq!(review.iter().map(|d| d.id).collect::<Vec<_>>(), input);

        // (b) FeatureOff => still no-op.
        col.set_config_json(
            "speedrun:review_interleave",
            &serde_json::json!({"mode": 1, "weights": [["calc", 0.9], ["linear_algebra", 0.1]]}),
            false,
        )?;
        let mut review = make_review(&ids);
        col.speedrun_interleave_reviews(&mut review)?;
        assert_eq!(review.iter().map(|d| d.id).collect::<Vec<_>>(), input);

        let due_before: Vec<i32> = ids
            .iter()
            .map(|(c, _)| col.storage.get_card(*c).unwrap().unwrap().due)
            .collect();

        // (c) Full => topic interleave reorders [calc1, calc2, la1] -> [calc1, la1, calc2].
        col.set_config_json(
            "speedrun:review_interleave",
            &serde_json::json!({"mode": 0, "weights": [["calc", 0.9], ["linear_algebra", 0.1]]}),
            false,
        )?;
        let mut review = make_review(&ids);
        col.speedrun_interleave_reviews(&mut review)?;
        assert_eq!(
            review.iter().map(|d| d.id).collect::<Vec<_>>(),
            vec![ids[0].0, ids[2].0, ids[1].0],
            "Full interleaves topics (no two adjacent same-topic)"
        );

        // Order-only safety: card scheduling state is untouched by the reorder.
        let due_after: Vec<i32> = ids
            .iter()
            .map(|(c, _)| col.storage.get_card(*c).unwrap().unwrap().due)
            .collect();
        assert_eq!(due_before, due_after, "interleave must not mutate card state");
        Ok(())
    }

    #[test]
    fn topic_index_uses_prefix_and_priority() {
        let weighted = vec![("calc".into(), 0.9), ("linear_algebra".into(), 0.1)];
        assert_eq!(
            topic_index_for_tags(&["calc::integration".into()], &weighted),
            Some(0)
        );
        assert_eq!(
            topic_index_for_tags(&["linear_algebra".into()], &weighted),
            Some(1)
        );
        assert_eq!(topic_index_for_tags(&["other".into()], &weighted), None);
    }

    #[test]
    fn reorder_new_full_interleaves_and_is_undo_safe() -> Result<()> {
        use anki_proto::speedrun::AblationMode;
        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        for (front, tag) in [("c1", "calc"), ("c2", "calc"), ("la1", "linear_algebra")] {
            let mut note = nt.new_note();
            note.set_field(0, front)?;
            col.add_note(&mut note, DeckId(1))?;
            note.tags = vec![tag.into()];
            col.update_note(&mut note)?;
        }
        // integrity-check API is col.storage.db_scalar::<String>("pragma
        // integrity_check")
        let before = col.storage.db_scalar::<String>("pragma integrity_check")?;
        assert_eq!(before, "ok");
        let weights = vec![
            ("calc".to_string(), 0.9),
            ("linear_algebra".to_string(), 0.1),
        ];
        let out = col.speedrun_reorder_new(DeckId(1), weights, AblationMode::Full)?;
        assert!(out.output >= 1);
        // integrity holds while the reposition is persisted (before undo)
        assert_eq!(
            col.storage.db_scalar::<String>("pragma integrity_check")?,
            "ok"
        );
        col.undo()?;
        assert_eq!(
            before,
            col.storage.db_scalar::<String>("pragma integrity_check")?
        );
        Ok(())
    }

    #[test]
    fn exam_profile_defaults_to_baked_in_gre_math_when_unset() -> Result<()> {
        let col = Collection::new();
        // fresh collection, nothing stored:
        let json = col.speedrun_exam_profile_json("gre_math");
        assert!(
            !json.is_empty(),
            "fresh collection must return a default profile"
        );
        assert!(
            json.contains("\"exam_id\""),
            "default must be the exam profile JSON"
        );
        assert!(
            json.contains("calc"),
            "default must contain the calc topics"
        );
        Ok(())
    }

    #[test]
    fn reorder_new_full_is_deterministic() -> Result<()> {
        // Contract: Full-mode reposition is a STABLE, repeatable permutation.
        // Two identically-built collections must yield byte-identical new-card
        // positions. Guards the ablation harness (3-build comparison is only
        // meaningful if Full is deterministic). interleave_by_topic's stability
        // is separately pinned by interleave_alternates_topics_no_two_adjacent_same.
        use anki_proto::speedrun::AblationMode;

        fn build_and_reorder() -> Result<Vec<i32>> {
            let mut col = Collection::new();
            let nt = col.get_notetype_by_name("Basic")?.unwrap();
            for front in ["c1", "c2", "c3", "la1", "la2"] {
                let tag = if front.starts_with('c') {
                    "calc"
                } else {
                    "linear_algebra"
                };
                let mut note = nt.new_note();
                note.set_field(0, front)?;
                col.add_note(&mut note, DeckId(1))?;
                note.tags = vec![tag.into()];
                col.update_note(&mut note)?;
            }
            let weights = vec![
                ("calc".to_string(), 0.9),
                ("linear_algebra".to_string(), 0.1),
            ];
            col.speedrun_reorder_new(DeckId(1), weights, AblationMode::Full)?;
            // Cards in insertion order (ids are monotonic within a fresh col);
            // element i is the new position assigned to the i-th inserted card.
            let mut cards = col.storage.get_all_cards();
            cards.sort_by_key(|c| c.id);
            Ok(cards.iter().map(|c| c.due).collect())
        }

        let a = build_and_reorder()?;
        let b = build_and_reorder()?;
        assert_eq!(a, b, "Full reorder must be deterministic across identical builds");
        // calc (weight .9) interleaved before linear_algebra (.1), within-topic
        // insertion order preserved => positions: c1=1,c2=3,c3=5, la1=2,la2=4.
        assert_eq!(a, vec![1, 3, 5, 2, 4], "expected weighted round-robin order");
        Ok(())
    }

    #[test]
    fn reorder_new_plain_is_noop() -> Result<()> {
        use anki_proto::speedrun::AblationMode;
        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, DeckId(1))?;
        let out = col.speedrun_reorder_new(DeckId(1), vec![], AblationMode::Plain)?;
        assert_eq!(out.output, 0);
        Ok(())
    }
}
