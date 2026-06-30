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

#[cfg(test)]
mod test {
    use super::coverage;
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
}
