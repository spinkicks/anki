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

/// Inactivity gap (ms) that separates two mini-mock SESSIONS. Graded
/// problem-attempt revlog entries closer together than this belong to the same
/// sitting; a gap >= this starts a new session. 30 minutes: a timed mini-mock is
/// a short focused burst, so half an hour of no graded attempts reliably marks a
/// new sitting while still tolerating think-time on a single hard problem.
///
/// Chosen as a documented module constant rather than a config field: threading
/// a new field through `ReadinessScoreConfig` + the exam-profile JSON schema +
/// defaults would be heavy for a value with no user-facing knob. Promote to
/// `ReadinessScoreConfig` if a future exam profile needs to tune it.
pub(crate) const SESSION_GAP_MS: i64 = 30 * 60 * 1000;

/// Count mini-mock SESSIONS from graded problem-attempt timestamps (epoch-ms).
/// A session is a maximal run of timestamps with no consecutive gap
/// >= `SESSION_GAP_MS`; it counts toward the total only if it holds
/// >= `min_items` attempts. Sorts `times` in place. Read-only w.r.t. the DB.
///
/// This replaces the old epoch-day bucketing, which collapsed two separate
/// same-day mini-mocks into one (under-counting the readiness give-up gate).
pub(crate) fn count_mock_sessions(times: &mut [i64], min_items: u32) -> u32 {
    if times.is_empty() {
        return 0;
    }
    times.sort_unstable();
    let mut sessions = 0u32;
    let mut run_len = 1u32;
    for i in 1..times.len() {
        if times[i] - times[i - 1] >= SESSION_GAP_MS {
            if run_len >= min_items {
                sessions += 1;
            }
            run_len = 1;
        } else {
            run_len += 1;
        }
    }
    if run_len >= min_items {
        sessions += 1;
    }
    sessions
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

/// Normal-approximation 95% confidence interval AROUND the MEAN of `values`
/// (each in [0, 1]) at the given z. Returns (lower, upper) clamped to [0, 1].
/// This is a CI on the mean itself (so the plotted point — the mean — always
/// lies inside the band), NOT a Wilson CI on a proportion. `n < 2` => (0.0,
/// 1.0) (full uncertainty; can't estimate a variance from < 2 samples), which
/// the caller treats as an abstain-like "no band" signal.
pub(crate) fn mean_ci(values: &[f64], z: f64) -> (f64, f64) {
    let n = values.len();
    if n < 2 {
        return (0.0, 1.0);
    }
    let n_f = n as f64;
    let mean = values.iter().sum::<f64>() / n_f;
    let sample_var = values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / (n_f - 1.0);
    let se = (sample_var / n_f).sqrt();
    (
        (mean - z * se).clamp(0.0, 1.0),
        (mean + z * se).clamp(0.0, 1.0),
    )
}

/// Given new-card note-ids each paired with their topic index (or None if the
/// card matches no weighted topic), and topic indices sorted by descending
/// points-at-stake, return the note-ids in interleaved order: round-robin
/// across topics in priority order.
///
/// BEST-EFFORT spread, NOT a hard guarantee. Each pass emits at most one card
/// per topic, so same-topic cards are spread as far apart as the topic mix
/// allows. This does NOT guarantee "no two same-topic cards are ever adjacent":
/// when one topic DOMINATES (has more cards than all others combined), its
/// surplus cards necessarily end up adjacent in the tail — that is the correct,
/// maximally-spread result, not a bug. No-adjacency holds only while at least
/// two topics still have cards remaining.
///
/// Unmatched cards (None) go last, in input order. Input order within a topic
/// is preserved (stable).
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
/// card belongs to (prefix rule: a card belongs to weighted topic `T` iff it
/// has a tag `== T` or a hierarchical descendant tag `T::...`).
/// `weighted` is (topic, weight) already sorted by descending weight, so the
/// FIRST match wins => the highest-priority topic when a card spans several.
///
/// Parent/container tags: a card tagged only with a container (e.g. `calc`, or
/// an intermediate `calc::single_var` that is NOT itself a weighted key) matches
/// the nearest ANCESTOR that IS a weighted topic — here `calc` — via the
/// `T::` prefix branch. It does NOT get promoted to a more specific descendant
/// leaf it lacks (there'd be no unambiguous choice, and the card genuinely has
/// no leaf tag). If no weighted topic is an ancestor-or-self of any tag, the
/// card belongs to NO topic (None) and the caller sends it to the unmatched
/// tail — never to a wrong / arbitrary bucket.
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
/// points-at-stake and interleaved by topic. Same-topic spread is BEST-EFFORT
/// (see `interleave_by_topic`): a dominant topic's surplus still trails
/// adjacently in the tail — no hard no-adjacency guarantee.
///
/// `points_at_stake = (1 - retrievability) * topic_weight` (weakness × weight).
/// Topics run in descending aggregate points-at-stake; within a topic the
/// weakest (highest points) card comes first; ties broken by `card_id` for
/// determinism. Cards with no weighted topic go last (weakest-first, then
/// card_id).
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

// ---- Scoring config (parsed from the exam-profile JSON; all fields defaulted
// so a profile with no "scoring" block still yields sane, documented defaults).
// ----

#[derive(Debug, Clone, Default, serde::Deserialize)]
#[serde(default)]
pub(crate) struct ScoringConfig {
    pub performance: PerfScoreConfig,
    pub readiness: ReadinessScoreConfig,
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(default)]
pub(crate) struct PerfScoreConfig {
    /// Minimum graded problem attempts on a topic before Performance reports a
    /// number (else abstain — memory != application, so we never fake it).
    pub min_problem_attempts: u32,
}
impl Default for PerfScoreConfig {
    fn default() -> Self {
        Self {
            min_problem_attempts: 5,
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(default)]
pub(crate) struct ReadinessScoreConfig {
    pub equating: EquatingConfig,
    pub conformal: ConformalConfig,
    pub give_up: GiveUpConfig,
    /// A "timed mini-mock" = a calendar day with >= this many problem attempts.
    pub mini_mock_min_items: u32,
}
impl Default for ReadinessScoreConfig {
    fn default() -> Self {
        Self {
            equating: EquatingConfig::default(),
            conformal: ConformalConfig::default(),
            give_up: GiveUpConfig::default(),
            mini_mock_min_items: 5,
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(default)]
pub(crate) struct EquatingConfig {
    pub min_scaled: f64,
    pub max_scaled: f64,
}
impl Default for EquatingConfig {
    fn default() -> Self {
        Self {
            min_scaled: 200.0,
            max_scaled: 990.0,
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(default)]
pub(crate) struct ConformalConfig {
    pub base_margin: f64,
    pub widen_k: f64,
}
impl Default for ConformalConfig {
    fn default() -> Self {
        Self {
            base_margin: 40.0,
            widen_k: 8.0,
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(default)]
pub(crate) struct GiveUpConfig {
    pub min_mini_mocks: u32,
    pub min_coverage: f64,
    pub max_interval_width: f64,
}
impl Default for GiveUpConfig {
    fn default() -> Self {
        Self {
            min_mini_mocks: 2,
            min_coverage: 0.6,
            max_interval_width: 200.0,
        }
    }
}

/// Parse `topic id -> ets_weight` from an exam-profile JSON string (missing =>
/// {}).
pub(crate) fn exam_topic_weights(profile_json: &str) -> std::collections::HashMap<String, f64> {
    #[derive(serde::Deserialize)]
    struct T {
        id: String,
        #[serde(default)]
        ets_weight: f64,
    }
    #[derive(serde::Deserialize)]
    struct P {
        #[serde(default)]
        topics: Vec<T>,
    }
    serde_json::from_str::<P>(profile_json)
        .map(|p| p.topics.into_iter().map(|t| (t.id, t.ets_weight)).collect())
        .unwrap_or_default()
}

/// Parse the `scoring` block from an exam-profile JSON string; missing/invalid
/// => documented defaults (never fails).
pub(crate) fn scoring_config_from_profile(profile_json: &str) -> ScoringConfig {
    #[derive(serde::Deserialize)]
    struct Wrapper {
        #[serde(default)]
        scoring: ScoringConfig,
    }
    serde_json::from_str::<Wrapper>(profile_json)
        .map(|w| w.scoring)
        .unwrap_or_default()
}

/// Weighted ability in [0,1] = Σ(weight × perf) / Σweight over topics that have
/// a Performance number. Returns None when no weighted topic has data (=>
/// abstain). This is the flat "calculus-weighted topic sum" (NOT a min()-gate).
pub(crate) fn weighted_ability(topic_perf: &[(f64, f64)]) -> Option<f64> {
    let total_w: f64 = topic_perf.iter().map(|(w, _)| w).sum();
    if total_w <= 0.0 {
        return None;
    }
    Some(topic_perf.iter().map(|(w, p)| w * p).sum::<f64>() / total_w)
}

/// Linear equating of ability [0,1] -> scaled [min, max] (GRE 200-990 by
/// default).
pub(crate) fn equate_linear(ability: f64, min_scaled: f64, max_scaled: f64) -> f64 {
    min_scaled + ability.clamp(0.0, 1.0) * (max_scaled - min_scaled)
}

/// Conformal-style half-margin (scaled points) that widens as attempts shrink:
/// `base * (1 + k/(n+1))`. n=0 => base*(1+k) (very uncertain); large n =>
/// ~base. Deterministic — no calibration set needed for the flat model.
pub(crate) fn conformal_margin(base: f64, k: f64, n: u32) -> f64 {
    base * (1.0 + k / (n as f64 + 1.0))
}

#[cfg(test)]
mod test {
    use super::coverage;
    use super::interleave_by_topic;
    use super::interleave_reviews_by_weakness;
    use super::mean_ci;
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
    fn mean_ci_point_lies_within_band() {
        // The mean (the plotted point) must always fall inside [lo, hi].
        let values = vec![0.8_f64, 0.9, 0.7, 0.85];
        let mean = values.iter().sum::<f64>() / values.len() as f64;
        let (lo, hi) = mean_ci(&values, 1.96);
        assert!(lo <= mean && mean <= hi, "mean {mean} not in [{lo}, {hi}]");
        assert!((0.0..=1.0).contains(&lo) && (0.0..=1.0).contains(&hi));
        assert!(lo < hi);
    }

    #[test]
    fn mean_ci_narrows_as_n_grows_for_same_mean() {
        // Same spread pattern, more samples => tighter CI (se ~ 1/sqrt(n)).
        let small = vec![0.6_f64, 0.8];
        let large = vec![0.6_f64, 0.8, 0.6, 0.8, 0.6, 0.8, 0.6, 0.8];
        // Both have mean 0.7.
        let (lo_s, hi_s) = mean_ci(&small, 1.96);
        let (lo_l, hi_l) = mean_ci(&large, 1.96);
        assert!(
            (hi_l - lo_l) < (hi_s - lo_s),
            "larger n should narrow: small width {} vs large width {}",
            hi_s - lo_s,
            hi_l - lo_l
        );
    }

    #[test]
    fn mean_ci_fewer_than_two_is_full_uncertainty() {
        assert_eq!(mean_ci(&[], 1.96), (0.0, 1.0));
        assert_eq!(mean_ci(&[0.9], 1.96), (0.0, 1.0));
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
            note.set_field(0, format!("q{i}"))?;
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
        assert!(
            !t.abstained,
            "24 graded reviews >= 20 with data => not abstained"
        );
        assert!(
            (0.0..=1.0).contains(&t.avg_recall),
            "avg_recall in [0,1]: {}",
            t.avg_recall
        );
        assert!(t.mastered_count <= t.cards_with_data);
        Ok(())
    }

    #[test]
    fn topic_mastery_excludes_problem_cards() -> Result<()> {
        // A topic with BOTH declarative cards and Speedrun::Problem cards: Memory
        // mastery is a DECLARATIVE-only signal, so the problem cards must NOT feed
        // cards_with_data / mastered_count / graded_reviews (regression for the
        // missing `-"tag:Speedrun::Problem"` exclusion in get_topic_mastery).
        use crate::card::FsrsMemoryState;
        use crate::revlog::RevlogEntry;
        use crate::revlog::RevlogId;

        let topic = "calc::integration";
        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();

        // Helper: add a card under `topic` with the given extra tags, a memory
        // state, and `reviews` graded revlog rows. Returns nothing; ids are local.
        let mut rid = 10_000i64;
        let mut add_card =
            |col: &mut Collection, extra_tags: &[&str], reviews: u32| -> Result<()> {
                let mut note = nt.new_note();
                note.set_field(0, format!("q{rid}"))?;
                col.add_note(&mut note, DeckId(1))?;
                let mut tags = vec![topic.to_string()];
                tags.extend(extra_tags.iter().map(|s| s.to_string()));
                note.tags = tags;
                col.update_note(&mut note)?;
                let cid = col.storage.all_cards_of_note(note.id)?.pop().unwrap().id;
                let mut card = col.storage.get_card(cid)?.unwrap();
                card.memory_state = Some(FsrsMemoryState {
                    stability: 1000.0,
                    difficulty: 5.0,
                });
                col.storage.update_card(&card)?;
                for _ in 0..reviews {
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
                Ok(())
            };

        // 2 declarative cards (12 graded reviews each = 24) + 1 problem card
        // (also with memory state + 12 graded reviews) under the SAME topic.
        add_card(&mut col, &[], 12)?;
        add_card(&mut col, &[], 12)?;
        add_card(&mut col, &["Speedrun::Problem"], 12)?;

        let resp = col.get_topic_mastery(anki_proto::speedrun::GetTopicMasteryRequest {
            topics: strs(&[topic]),
            mastery_threshold: 0.0, // => default 0.9
            min_reviews: 0,         // => default 20
        })?;
        let t = &resp.topics[0];
        assert_eq!(
            t.cards_with_data, 2,
            "only the 2 declarative cards count (problem card excluded)"
        );
        assert_eq!(
            t.graded_reviews, 24,
            "only the 24 declarative reviews count (problem reviews excluded)"
        );
        assert!(
            t.mastered_count <= 2,
            "mastered_count is over declarative cards only"
        );
        Ok(())
    }

    #[test]
    fn interleave_spreads_topics_round_robin() {
        // Balanced-ish mix: round-robin spreads topics so same-topic cards are as
        // far apart as the mix allows. Topic 0 has one surplus card (3 vs 2) so it
        // trails at the end — the tail spread is best-effort, not magic.
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
    fn interleave_is_best_effort_not_hard_no_adjacency() {
        // FIX 4 (honesty): interleave_by_topic does NOT guarantee "no two
        // same-topic cards are ever adjacent". When one topic DOMINATES (more
        // cards than all others combined), its surplus MUST land adjacent in the
        // tail. Assert the real, maximally-spread output AND that same-topic
        // adjacency genuinely occurs — so the contract stays honest.
        let nt = vec![
            (1, Some(0)),
            (2, Some(0)),
            (3, Some(0)),
            (4, Some(0)),
            (10, Some(1)),
        ];
        let out = interleave_by_topic(&[0, 1], &nt);
        // Round-robin: 0,1 then 0 (topic 1 exhausted) then 0, 0. Topic 0's tail is
        // adjacent to itself — expected best-effort spread, not a guarantee.
        assert_eq!(out, vec![1, 10, 2, 3, 4]);
        let topics: Vec<usize> = out
            .iter()
            .map(|nid| nt.iter().find(|(n, _)| n == nid).unwrap().1.unwrap())
            .collect();
        assert!(
            topics.windows(2).any(|w| w[0] == w[1]),
            "a dominant topic PRODUCES same-topic adjacency; no-adjacency is not guaranteed"
        );
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
            (1, Some(0), 0.2),  // calc  points=.72
            (2, Some(0), 0.5),  // calc  points=.45
            (3, Some(1), 0.9),  // la    points=.01
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
        for (front, tag) in [
            ("calc1", "calc"),
            ("calc2", "calc"),
            ("la1", "linear_algebra"),
        ] {
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

        // (c) Full => topic interleave reorders [calc1, calc2, la1] -> [calc1, la1,
        // calc2].
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
            "Full interleaves topics (best-effort spread; here fully alternates)"
        );

        // Order-only safety: card scheduling state is untouched by the reorder.
        let due_after: Vec<i32> = ids
            .iter()
            .map(|(c, _)| col.storage.get_card(*c).unwrap().unwrap().due)
            .collect();
        assert_eq!(
            due_before, due_after,
            "interleave must not mutate card state"
        );
        Ok(())
    }

    #[test]
    fn weighted_ability_is_weighted_mean() {
        assert_eq!(
            super::weighted_ability(&[(0.9, 1.0), (0.1, 0.0)]),
            Some(0.9)
        );
        assert_eq!(super::weighted_ability(&[]), None);
    }

    #[test]
    fn equate_linear_maps_unit_to_scale() {
        assert!((super::equate_linear(0.0, 200.0, 990.0) - 200.0).abs() < 1e-9);
        assert!((super::equate_linear(1.0, 200.0, 990.0) - 990.0).abs() < 1e-9);
        assert!((super::equate_linear(0.5, 200.0, 990.0) - 595.0).abs() < 1e-9);
    }

    #[test]
    fn conformal_margin_widens_when_sparse() {
        let sparse = super::conformal_margin(40.0, 8.0, 0);
        let dense = super::conformal_margin(40.0, 8.0, 100);
        assert!(
            sparse > dense,
            "sparse {sparse} should exceed dense {dense}"
        );
        assert!((dense - 40.0 * (1.0 + 8.0 / 101.0)).abs() < 1e-9);
    }

    #[test]
    fn scoring_config_parses_from_default_profile() {
        let col = Collection::new();
        let json = col.speedrun_exam_profile_json("gre_math");
        let cfg = super::scoring_config_from_profile(&json);
        assert_eq!(cfg.performance.min_problem_attempts, 5);
        assert_eq!(cfg.readiness.give_up.min_mini_mocks, 2);
        assert!((cfg.readiness.equating.max_scaled - 990.0).abs() < 1e-9);
    }

    // ---- Session grouping (FIX C: mini_mock_count is session-scoped) ----

    #[test]
    fn count_mock_sessions_same_day_two_sessions() {
        // Two bursts on the SAME epoch-day, separated by more than SESSION_GAP_MS
        // (the old day-bucketing collapsed these into 1). Each burst has 5 tightly
        // spaced attempts (1 ms apart) -> 2 sessions of 5 >= min 5.
        let day = 5i64 * 86_400_000;
        let mut times: Vec<i64> = Vec::new();
        // Burst A occupies day..=day+4.
        times.extend(day..day + 5);
        // Burst B starts a full SESSION_GAP_MS after burst A's LAST attempt
        // (day+4), so the A->B gap is > SESSION_GAP_MS and a new session starts.
        let b = day + 4 + super::SESSION_GAP_MS + 1;
        times.extend(b..b + 5);
        assert_eq!(super::count_mock_sessions(&mut times, 5), 2);
    }

    #[test]
    fn count_mock_sessions_tight_cluster_one_session() {
        // 10 attempts all within SESSION_GAP_MS (1 ms apart) -> a single session.
        let mut times: Vec<i64> = (1_000..1_010).collect();
        assert_eq!(super::count_mock_sessions(&mut times, 5), 1);
    }

    #[test]
    fn count_mock_sessions_below_min_items_not_counted() {
        // A session with fewer than min_items attempts does NOT count. Burst A has
        // 5 (counts), burst B has only 3 (does not) -> total 1.
        let mut times: Vec<i64> = Vec::new();
        times.extend(0i64..5); // 5 attempts
        let b = super::SESSION_GAP_MS + 100;
        times.extend(b..b + 3); // 3 attempts, separate session
        assert_eq!(super::count_mock_sessions(&mut times, 5), 1);
    }

    #[test]
    fn count_mock_sessions_boundary_and_unsorted() {
        // A gap of EXACTLY SESSION_GAP_MS starts a new session (>= is the rule),
        // and unsorted input is handled (sorted in place).
        let mut times = vec![super::SESSION_GAP_MS, 0, 1, super::SESSION_GAP_MS + 1];
        // sorted: [0, 1, GAP, GAP+1] -> gap between 1 and GAP is (GAP-1) < GAP so
        // same session; so this is one run of 4. Use min 2 -> 1 session.
        assert_eq!(super::count_mock_sessions(&mut times, 2), 1);
        // Now force a boundary: [0, GAP] -> gap == GAP -> two singleton sessions.
        let mut edge = vec![super::SESSION_GAP_MS, 0];
        assert_eq!(super::count_mock_sessions(&mut edge, 1), 2);
    }

    #[test]
    fn count_mock_sessions_empty_is_zero() {
        let mut times: Vec<i64> = Vec::new();
        assert_eq!(super::count_mock_sessions(&mut times, 1), 0);
    }

    // ---- Scoring integration (synthetic problem revlog) ----

    // Add `count` graded problem attempts to `cid` starting at epoch-day `day`
    // (revlog ids = day*86_400_000 + i). `correct` of them use button 4, rest 1.
    fn add_problem_attempts(
        col: &mut Collection,
        cid: crate::prelude::CardId,
        day: i64,
        count: u32,
        correct: u32,
    ) {
        use crate::revlog::RevlogEntry;
        use crate::revlog::RevlogId;
        for i in 0..count {
            let button = if i < correct { 4 } else { 1 };
            col.storage
                .add_revlog_entry(
                    &RevlogEntry {
                        id: RevlogId(day * 86_400_000 + i as i64),
                        cid,
                        button_chosen: button,
                        ..Default::default()
                    },
                    false,
                )
                .unwrap();
        }
    }

    // Add `count` graded problem attempts to `cid` at explicit epoch-ms
    // `base_ms + i` (i.e. 1 ms apart -> a single tight session). Lets a test
    // place two bursts on the SAME day but separated by a chosen gap.
    fn add_problem_attempts_at_ms(
        col: &mut Collection,
        cid: crate::prelude::CardId,
        base_ms: i64,
        count: u32,
    ) {
        use crate::revlog::RevlogEntry;
        use crate::revlog::RevlogId;
        for i in 0..count {
            col.storage
                .add_revlog_entry(
                    &RevlogEntry {
                        id: RevlogId(base_ms + i as i64),
                        cid,
                        button_chosen: 4,
                        ..Default::default()
                    },
                    false,
                )
                .unwrap();
        }
    }

    fn add_problem_card(col: &mut Collection, topic: &str, front: &str) -> crate::prelude::CardId {
        let nt = col.get_notetype_by_name("Basic").unwrap().unwrap();
        let mut note = nt.new_note();
        note.set_field(0, front).unwrap();
        col.add_note(&mut note, DeckId(1)).unwrap();
        note.tags = vec![topic.into(), "Speedrun::Problem".into()];
        col.update_note(&mut note).unwrap();
        col.storage
            .all_cards_of_note(note.id)
            .unwrap()
            .pop()
            .unwrap()
            .id
    }

    #[test]
    fn performance_scores_and_gap_delta_with_problems() -> Result<()> {
        use crate::card::FsrsMemoryState;
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        // A declarative card with a memory state => a recall signal for the gap.
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut d = nt.new_note();
        d.set_field(0, "decl")?;
        col.add_note(&mut d, DeckId(1))?;
        d.tags = vec![topic.into()];
        col.update_note(&mut d)?;
        let dcid = col.storage.all_cards_of_note(d.id)?.pop().unwrap().id;
        let mut dc = col.storage.get_card(dcid)?.unwrap();
        dc.memory_state = Some(FsrsMemoryState {
            stability: 1000.0,
            difficulty: 5.0,
        });
        col.storage.update_card(&dc)?;
        // A problem card with 10 graded attempts, 9 correct => accuracy 0.9.
        let pcid = add_problem_card(&mut col, topic, "prob");
        add_problem_attempts(&mut col, pcid, 5, 10, 9);

        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        assert!(
            !resp.scaffolding,
            "a real Performance number => not scaffolding"
        );
        let t = &resp.topics[0];
        let perf = t.performance.as_ref().unwrap();
        assert!(!perf.abstained, "10 attempts >= min 5 => scored");
        assert!((perf.point - 0.9).abs() < 1e-9, "accuracy={}", perf.point);
        assert!(perf.lower < perf.point && perf.point < perf.upper); // Wilson band
        assert_eq!(perf.scale, anki_proto::speedrun::ScoreScale::Unit as i32);
        // gap_delta = declarative recall - problem accuracy; computed (both present).
        assert!(t.gap_delta.abs() <= 1.0, "gap_delta={}", t.gap_delta);
        Ok(())
    }

    #[test]
    fn performance_abstains_below_attempt_threshold() -> Result<()> {
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        let pcid = add_problem_card(&mut col, topic, "prob");
        add_problem_attempts(&mut col, pcid, 5, 3, 3); // only 3 attempts (< 5)
        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        assert!(resp.topics[0].performance.as_ref().unwrap().abstained);
        assert!(resp.scaffolding, "nothing scored => still scaffolding");
        Ok(())
    }

    #[test]
    fn readiness_abstains_without_two_mini_mocks() -> Result<()> {
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        let pcid = add_problem_card(&mut col, topic, "prob");
        add_problem_attempts(&mut col, pcid, 5, 10, 9); // 10 attempts, ALL on day 5
        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        let overall = resp.overall_readiness.as_ref().unwrap();
        assert!(overall.abstained, "1 mini-mock (< 2) => readiness locked");
        assert!(!resp.abstain_reason.is_empty());
        assert!(
            resp.unlock_requirements
                .iter()
                .any(|u| u.kind == "mini_mocks"),
            "unlock must name the missing mini-mocks"
        );
        Ok(())
    }

    #[test]
    fn readiness_unlocks_with_two_mocks_and_coverage() -> Result<()> {
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        let pcid = add_problem_card(&mut col, topic, "prob");
        // 2 mini-mocks: 5 attempts on day 5 + 5 on day 6 (each >= mini_mock_min 5).
        add_problem_attempts(&mut col, pcid, 5, 5, 5);
        add_problem_attempts(&mut col, pcid, 6, 5, 4);
        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        let overall = resp.overall_readiness.as_ref().unwrap();
        assert!(
            !overall.abstained,
            "2 mocks + full coverage + tight interval => unlocked; reason={}",
            resp.abstain_reason
        );
        assert_eq!(
            overall.scale,
            anki_proto::speedrun::ScoreScale::Gre200990 as i32
        );
        assert!(
            (200.0..=990.0).contains(&overall.point),
            "scaled score in range: {}",
            overall.point
        );
        assert!(overall.lower <= overall.point && overall.point <= overall.upper);
        // FIX 2: percentile abstains (no ETS norm table) — never a fabricated number.
        assert_eq!(
            overall.percentile, 0.0,
            "readiness percentile abstains (no ETS norm table)"
        );
        Ok(())
    }

    #[test]
    fn readiness_counts_two_same_day_sessions_as_two_mocks() -> Result<()> {
        // Regression for FIX C: two SEPARATE mini-mocks on the SAME calendar day
        // (bursts > SESSION_GAP_MS apart) must count as 2 sessions, so the give-up
        // gate's `min_mini_mocks` (2) is satisfied and readiness UNLOCKS. Under the
        // old epoch-day bucketing both bursts collapsed to 1 day => stayed locked.
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        let pcid = add_problem_card(&mut col, topic, "prob");
        // Both bursts on day 5, separated by > 30 min; 5 attempts each (>= min 5).
        // Burst A occupies day5..=day5+4; burst B starts a full SESSION_GAP_MS
        // after A's last attempt so the A->B gap exceeds SESSION_GAP_MS.
        let day5 = 5i64 * 86_400_000;
        add_problem_attempts_at_ms(&mut col, pcid, day5, 5);
        add_problem_attempts_at_ms(&mut col, pcid, day5 + 4 + super::SESSION_GAP_MS + 1, 5);

        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        // No mini_mocks unlock requirement should remain (2 sessions satisfy it).
        assert!(
            !resp
                .unlock_requirements
                .iter()
                .any(|u| u.kind == "mini_mocks"),
            "two same-day sessions must satisfy min_mini_mocks; unlocks={:?}",
            resp.unlock_requirements
                .iter()
                .map(|u| &u.kind)
                .collect::<Vec<_>>()
        );
        let overall = resp.overall_readiness.as_ref().unwrap();
        assert!(
            !overall.abstained,
            "2 same-day sessions + full coverage + tight interval => unlocked; reason={}",
            resp.abstain_reason
        );
        Ok(())
    }

    #[test]
    fn readiness_same_session_burst_counts_as_one_mock() -> Result<()> {
        // Complement: a SINGLE tight burst of 10 same-day attempts is one session,
        // so readiness stays LOCKED on min_mini_mocks (only 1 mock). This pins the
        // "within SESSION_GAP_MS => one session" half of the fix end-to-end.
        let topic = "calc::single_var::integration";
        let mut col = Collection::new();
        let pcid = add_problem_card(&mut col, topic, "prob");
        add_problem_attempts_at_ms(&mut col, pcid, 5i64 * 86_400_000, 10);

        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![topic.into()],
            })?;
        assert!(
            resp.unlock_requirements
                .iter()
                .any(|u| u.kind == "mini_mocks"),
            "one tight burst is a single session (< 2 mocks) => still locked"
        );
        Ok(())
    }

    #[test]
    fn readiness_coverage_is_problem_based_not_declarative() -> Result<()> {
        // Regression for FIX 3: coverage must count only topics with enough timed
        // PROBLEM attempts, not declarative flashcard study. Two topics:
        //  - covered_topic: a problem card with 10 attempts (>= min 5)  => covered
        //  - decl_topic:    only a declarative card w/ memory state (attempts=0) => NOT
        //    covered, even though it has recall data.
        // => coverage 1/2 = 0.5 < min_coverage 0.6, so readiness stays locked with
        // a "coverage" unlock requirement.
        use crate::card::FsrsMemoryState;
        let covered_topic = "calc::single_var::integration";
        let decl_topic = "linear_algebra::eigen";
        let mut col = Collection::new();

        // decl_topic: declarative card with a memory state, NO problem attempts.
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut d = nt.new_note();
        d.set_field(0, "decl")?;
        col.add_note(&mut d, DeckId(1))?;
        d.tags = vec![decl_topic.into()];
        col.update_note(&mut d)?;
        let dcid = col.storage.all_cards_of_note(d.id)?.pop().unwrap().id;
        let mut dc = col.storage.get_card(dcid)?.unwrap();
        dc.memory_state = Some(FsrsMemoryState {
            stability: 1000.0,
            difficulty: 5.0,
        });
        col.storage.update_card(&dc)?;

        // covered_topic: a problem card with 2 mini-mocks worth of attempts so the
        // ONLY thing that could keep readiness locked is coverage.
        let pcid = add_problem_card(&mut col, covered_topic, "prob");
        add_problem_attempts(&mut col, pcid, 5, 5, 5);
        add_problem_attempts(&mut col, pcid, 6, 5, 4);

        let resp =
            col.get_performance_readiness(anki_proto::speedrun::GetPerformanceReadinessRequest {
                topics: vec![covered_topic.into(), decl_topic.into()],
            })?;
        let overall = resp.overall_readiness.as_ref().unwrap();
        assert!(
            overall.abstained,
            "coverage 1/2 (declarative topic doesn't count) < 0.6 => locked"
        );
        let cov = resp
            .unlock_requirements
            .iter()
            .find(|u| u.kind == "coverage")
            .expect("a coverage unlock requirement must be present");
        assert!(
            (cov.have - 0.5).abs() < 1e-9,
            "coverage counts only the problem topic: have={}",
            cov.have
        );
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
    fn topic_index_parent_and_container_tags_map_correctly() {
        // FIX 3: ground how PARENT/container tags map. After grounding the real
        // GRE-math profile there is NO correctness defect here — the prefix rule
        // already assigns container tags to the nearest weighted ancestor (or to
        // None). These asserts LOCK that behavior so a future refactor can't
        // silently regress it into a wrong index or an arbitrary 0-weight bucket.
        //
        // Weights sorted DESCENDING (as the callers sort them): leaves first,
        // the weight-0 `calc` container LAST.
        let weighted = vec![
            ("calc::single_var::integration".into(), 0.16),
            ("calc::single_var::differentiation".into(), 0.14),
            ("calc::limits".into(), 0.10),
            ("calc".into(), 0.0),
        ];
        let idx = |t: &str| topic_index_for_tags(&[t.into()], &weighted);

        // Exact leaf tag => that leaf.
        assert_eq!(idx("calc::single_var::integration"), Some(0));
        // Descendant BELOW a leaf => still that leaf (deeper card tags roll up).
        assert_eq!(idx("calc::single_var::integration::by_parts"), Some(0));
        // Intermediate container `calc::single_var` is NOT a weighted key: it must
        // map to its nearest weighted ANCESTOR `calc` (index 3), NOT to a leaf it
        // never carries. This is the exact "parent tag" case from the ticket — it
        // lands in `calc` (the true ancestor), not a wrong leaf bucket.
        assert_eq!(
            idx("calc::single_var"),
            Some(3),
            "intermediate container maps to nearest weighted ancestor (calc), not a leaf"
        );
        // Top container tag `calc` => the `calc` bucket itself (index 3).
        assert_eq!(idx("calc"), Some(3));
        // A card with no ancestor-or-self among weighted topics => None (unmatched
        // tail), never a wrong bucket. Substring is NOT a prefix match.
        assert_eq!(idx("calculus_tricks"), None);
        assert_eq!(idx("probability"), None);
    }

    #[test]
    fn topic_index_no_container_key_parent_tag_is_none() {
        // Complement to the above: when the container is NOT itself a weighted
        // topic, a card tagged ONLY with that container (or an intermediate under
        // it) belongs to NO weighted topic => None. Here `calc` is absent from the
        // weights, so `calc::single_var` has no weighted ancestor-or-self.
        let weighted = vec![
            ("calc::single_var::integration".into(), 0.16),
            ("calc::limits".into(), 0.10),
        ];
        let idx = |t: &str| topic_index_for_tags(&[t.into()], &weighted);
        // No weighted ancestor => unmatched (None), NOT a 0-weight fallback.
        assert_eq!(idx("calc"), None);
        assert_eq!(idx("calc::single_var"), None);
        // A real leaf still matches.
        assert_eq!(idx("calc::limits"), Some(1));
    }

    #[test]
    fn topic_index_priority_picks_highest_weight_when_card_spans_topics() {
        // Priority semantics lock: a card carrying tags for BOTH a high- and a
        // low-weight topic must map to the HIGHER-weight one (first in the
        // descending-sorted list), independent of tag ordering on the card.
        let weighted = vec![
            ("calc::single_var::integration".into(), 0.16),
            ("calc::limits".into(), 0.10),
        ];
        assert_eq!(
            topic_index_for_tags(
                &[
                    "calc::limits".into(),
                    "calc::single_var::integration".into()
                ],
                &weighted
            ),
            Some(0),
            "highest-weight topic wins regardless of tag order"
        );
        assert_eq!(
            topic_index_for_tags(
                &[
                    "calc::single_var::integration".into(),
                    "calc::limits".into()
                ],
                &weighted
            ),
            Some(0)
        );
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
        // is separately pinned by interleave_spreads_topics_round_robin.
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
        assert_eq!(
            a, b,
            "Full reorder must be deterministic across identical builds"
        );
        // calc (weight .9) interleaved before linear_algebra (.1), within-topic
        // insertion order preserved => positions: c1=1,c2=3,c3=5, la1=2,la2=4.
        assert_eq!(
            a,
            vec![1, 3, 5, 2, 4],
            "expected weighted round-robin order"
        );
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

    #[test]
    fn reorder_new_full_no_signal_is_noop() -> Result<()> {
        // FIX 1: Full mode has NO ordering signal when there are no positive
        // topic weights (empty OR all <= 0). It must NO-OP like Plain — return 0
        // and leave every new-card position untouched — instead of churning
        // positions by dumping all cards into the unmatched tail.
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
        fn positions(col: &Collection) -> Vec<i32> {
            let mut cards = col.storage.get_all_cards();
            cards.sort_by_key(|c| c.id);
            cards.iter().map(|c| c.due).collect()
        }
        let before = positions(&col);

        // (a) Empty weights => no-op (0 changes, positions unchanged).
        let out = col.speedrun_reorder_new(DeckId(1), vec![], AblationMode::Full)?;
        assert_eq!(out.output, 0, "empty weights => Full no-ops");
        assert_eq!(
            before,
            positions(&col),
            "empty weights => no position churn"
        );

        // (b) All-zero weights => also a no-op (no meaningful ordering signal).
        let zero_weights = vec![
            ("calc".to_string(), 0.0),
            ("linear_algebra".to_string(), 0.0),
        ];
        let out = col.speedrun_reorder_new(DeckId(1), zero_weights, AblationMode::Full)?;
        assert_eq!(out.output, 0, "all-zero weights => Full no-ops");
        assert_eq!(
            before,
            positions(&col),
            "all-zero weights => no position churn"
        );
        Ok(())
    }

    #[test]
    fn reorder_new_feature_off_still_reposition_with_empty_weights() -> Result<()> {
        // FIX 1 boundary: the empty/zero-weight no-op guard is Full-ONLY. FeatureOff
        // is the ablation BASELINE whose ordering signal is note-id, not weights, so
        // it must STILL reposition (by sorted note id) even with empty weights.
        use anki_proto::speedrun::AblationMode;
        let mut col = Collection::new();
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        for front in ["a", "b", "c"] {
            let mut note = nt.new_note();
            note.set_field(0, front)?;
            col.add_note(&mut note, DeckId(1))?;
        }
        // Empty weights: FeatureOff repositions all 3 by note-id (baseline), so
        // the op reports a non-zero count (control arm stays intact).
        let out = col.speedrun_reorder_new(DeckId(1), vec![], AblationMode::FeatureOff)?;
        assert!(
            out.output >= 1,
            "FeatureOff baseline repositions by note-id even with empty weights; got {}",
            out.output
        );
        Ok(())
    }
}
