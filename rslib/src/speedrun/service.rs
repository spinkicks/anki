// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use crate::collection::Collection;
use crate::error;
use crate::prelude::*;
use crate::search::JoinSearches;
use crate::search::SearchNode;
use crate::search::SortMode;
use crate::search::StateKind;

impl Collection {
    /// Reposition new cards in `deck_id` by points-at-stake + topic interleave.
    /// Persisted, undoable (Op::SortCards). New-card positions only.
    pub(crate) fn speedrun_reorder_new(
        &mut self,
        deck_id: DeckId,
        mut topic_weights: Vec<(String, f64)>,
        mode: anki_proto::speedrun::AblationMode,
    ) -> Result<OpOutput<usize>> {
        use anki_proto::speedrun::AblationMode;
        // Plain Anki: do nothing (empty op).
        if mode == AblationMode::Plain {
            return self.transact(Op::SortCards, |_col| Ok(0));
        }
        // Gather this deck's new cards (children included), in note-id order.
        let cids = self.search_cards(
            SearchNode::from_deck_id(deck_id, true).and(StateKind::New),
            SortMode::NoOrder,
        )?;
        let usn = self.usn()?;
        self.transact(Op::SortCards, |col| {
            let cards = col.all_cards_for_ids(&cids, false)?;
            let ordered_nids: Vec<i64> = if mode == AblationMode::FeatureOff {
                let mut nids: Vec<i64> = cards.iter().map(|c| c.note_id.0).collect();
                nids.sort_unstable();
                nids.dedup();
                nids
            } else {
                topic_weights
                    .sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                let mut note_topic: Vec<(i64, Option<usize>)> = Vec::new();
                let mut seen = std::collections::HashSet::new();
                for c in &cards {
                    if seen.insert(c.note_id) {
                        let note = col.storage.get_note(c.note_id)?.or_not_found(c.note_id)?;
                        note_topic.push((
                            c.note_id.0,
                            crate::speedrun::topic_index_for_tags(&note.tags, &topic_weights),
                        ));
                    }
                }
                let ordered_topics: Vec<usize> = (0..topic_weights.len()).collect();
                crate::speedrun::interleave_by_topic(&ordered_topics, &note_topic)
            };
            // Assign positions 1..N by note order, mirroring sort_cards_inner.
            let pos: std::collections::HashMap<i64, u32> = ordered_nids
                .iter()
                .enumerate()
                .map(|(i, nid)| (*nid, (i as u32) + 1))
                .collect();
            let mut count = 0;
            for mut card in cards {
                let original = card.clone();
                if let Some(p) = pos.get(&card.note_id.0) {
                    if card.set_new_position_speedrun(*p) {
                        count += 1;
                        col.update_card_inner(&mut card, original, usn)?;
                    }
                }
            }
            Ok(count)
        })
    }
}

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
        use crate::speedrun::topic_aggregate;
        use crate::speedrun::wilson_interval;
        use crate::speedrun::MASTERY_THRESHOLD_DEFAULT;
        use crate::speedrun::MIN_REVIEWS_DEFAULT;
        use crate::speedrun::WILSON_Z_95;

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
            // Batch (was N+1): one search populates the `search_cids` table, then a
            // SINGLE card scan and a SINGLE revlog scan over that set — instead of
            // get_card + get_revlog_entries_for_card per card. Values are identical
            // (guarded by topic_mastery_scores_with_reviews_and_memory_state).
            let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;

            let mut retrievabilities: Vec<f64> = Vec::new();
            guard.col.storage.for_each_card_in_search(|card| {
                if let Some(state) = card.memory_state {
                    let elapsed = card.seconds_since_last_review(&timing).unwrap_or_default();
                    let decay = card.decay.unwrap_or(FSRS5_DEFAULT_DECAY);
                    let r = fsrs.current_retrievability_seconds(state.into(), elapsed, decay);
                    retrievabilities.push(r as f64);
                }
                Ok(())
            })?;
            let graded_reviews = guard
                .col
                .storage
                .get_revlog_entries_for_searched_cards()?
                .iter()
                .filter(|e| e.has_rating_and_affects_scheduling())
                .count() as u32;
            drop(guard);

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

    fn get_exam_profile(
        &mut self,
        input: anki_proto::speedrun::GetExamProfileRequest,
    ) -> error::Result<anki_proto::speedrun::ExamProfileResponse> {
        let exam_id = if input.exam_id.is_empty() {
            "gre_math".to_string()
        } else {
            input.exam_id.clone()
        };
        Ok(anki_proto::speedrun::ExamProfileResponse {
            profile_json: self.speedrun_exam_profile_json(&exam_id),
            exam_id,
        })
    }

    fn reorder_new_by_points_at_stake(
        &mut self,
        input: anki_proto::speedrun::ReorderNewRequest,
    ) -> error::Result<anki_proto::collection::OpChangesWithCount> {
        let weights = input
            .topic_weights
            .into_iter()
            .map(|tw| (tw.topic, tw.weight))
            .collect();
        let mode = anki_proto::speedrun::AblationMode::try_from(input.mode)
            .unwrap_or(anki_proto::speedrun::AblationMode::Full);
        self.speedrun_reorder_new(DeckId(input.deck_id), weights, mode)
            .map(Into::into)
    }

    fn get_performance_readiness(
        &mut self,
        input: anki_proto::speedrun::GetPerformanceReadinessRequest,
    ) -> error::Result<anki_proto::speedrun::PerformanceReadinessResponse> {
        use anki_proto::speedrun::ScoreScaffold;
        use anki_proto::speedrun::TopicScaffold;
        let abstain = || ScoreScaffold {
            point: 0.0,
            lower: 0.0,
            upper: 1.0,
            abstained: true,
        };
        let topics = input
            .topics
            .into_iter()
            .map(|t| TopicScaffold {
                topic: t,
                performance: Some(abstain()),
                readiness: Some(abstain()),
            })
            .collect();
        Ok(anki_proto::speedrun::PerformanceReadinessResponse {
            scaffolding: true,
            topics,
            overall_readiness: Some(abstain()),
        })
    }
}
