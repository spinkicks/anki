// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use crate::collection::Collection;
use crate::error;

impl crate::services::SpeedrunService for Collection {
    fn get_coverage(
        &mut self,
        input: anki_proto::speedrun::GetCoverageRequest,
    ) -> error::Result<anki_proto::speedrun::CoverageResponse> {
        let all_tags: Vec<String> = self
            .storage
            .all_tags()?
            .into_iter()
            .map(|t| t.name)
            .collect();
        let (covered, total) = crate::speedrun::coverage(&all_tags, &input.required_tags);
        let percent = if total == 0 {
            0.0
        } else {
            (covered as f64) / (total as f64) * 100.0
        };
        Ok(anki_proto::speedrun::CoverageResponse {
            covered,
            total,
            percent,
            backend_version: crate::version::version().to_string(),
        })
    }
}
