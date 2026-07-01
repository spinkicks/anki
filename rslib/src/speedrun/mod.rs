// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

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
/// Default minimum graded reviews before a topic reports a (non-abstained) score.
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

#[cfg(test)]
mod test {
    use super::coverage;
    use super::topic_aggregate;
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
}
