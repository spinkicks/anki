// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use crate::collection::Collection;
use crate::error;
use crate::search::SortMode;

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

    fn get_topic_mastery(
        &mut self,
        input: anki_proto::speedrun::GetTopicMasteryRequest,
    ) -> error::Result<anki_proto::speedrun::TopicMasteryResponse> {
        use crate::speedrun::{
            topic_aggregate, wilson_interval, MASTERY_THRESHOLD_DEFAULT, MIN_REVIEWS_DEFAULT,
            WILSON_Z_95,
        };

        let threshold = if input.mastery_threshold <= 0.0 {
            MASTERY_THRESHOLD_DEFAULT
        } else {
            input.mastery_threshold
        };
        let min_reviews = if input.min_reviews == 0 {
            MIN_REVIEWS_DEFAULT
        } else {
            input.min_reviews
        };

        let timing = self.timing_today()?;
        let fsrs = FSRS::new(None).unwrap();

        let mut out = Vec::with_capacity(input.topics.len());
        for topic in &input.topics {
            // Cards tagged exactly `topic` OR any hierarchical descendant `topic::*`.
            let search = format!("(\"tag:{topic}\" OR \"tag:{topic}::*\")");
            let cids = self.search_cards(search.as_str(), SortMode::NoOrder)?;

            let mut retrievabilities: Vec<f64> = Vec::new();
            let mut graded_reviews: u32 = 0;
            for cid in cids {
                let card = match self.storage.get_card(cid)? {
                    Some(c) => c,
                    None => continue,
                };
                if let Some(state) = card.memory_state {
                    let elapsed = card.seconds_since_last_review(&timing).unwrap_or_default();
                    let decay = card.decay.unwrap_or(FSRS5_DEFAULT_DECAY);
                    let r = fsrs.current_retrievability_seconds(state.into(), elapsed, decay);
                    retrievabilities.push(r as f64);
                }
                graded_reviews += self
                    .storage
                    .get_revlog_entries_for_card(cid)?
                    .iter()
                    .filter(|e| e.has_rating_and_affects_scheduling())
                    .count() as u32;
            }

            let (cards_with_data, mastered_count, avg_recall) =
                topic_aggregate(&retrievabilities, threshold);
            let (mastered_lower, mastered_upper) =
                wilson_interval(mastered_count, cards_with_data, WILSON_Z_95);
            let abstained = graded_reviews < min_reviews || cards_with_data == 0;

            out.push(anki_proto::speedrun::TopicMastery {
                topic: topic.clone(),
                cards_with_data,
                mastered_count,
                avg_recall,
                mastered_lower,
                mastered_upper,
                graded_reviews,
                abstained,
            });
        }

        Ok(anki_proto::speedrun::TopicMasteryResponse {
            topics: out,
            backend_version: crate::version::version().to_string(),
        })
    }
}
