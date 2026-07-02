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
        use crate::speedrun::mean_ci;
        use crate::speedrun::topic_aggregate;
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
            // Cards tagged exactly `topic` OR any hierarchical descendant `topic::*`,
            // EXCLUDING MCQ problem cards (mirror `topic_recall`): Memory mastery is
            // a DECLARATIVE-only signal, so retrievabilities + graded_reviews must not
            // be contaminated by Speedrun::Problem cards.
            let search =
                format!("(\"tag:{topic}\" OR \"tag:{topic}::*\") -\"tag:Speedrun::Problem\"");
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
            // The UI plots `avg_recall` (mean FSRS retrievability) as the point of
            // the Memory RANGE band, so the band must be a CI on that SAME quantity.
            // Proto is frozen: the `mastered_lower`/`mastered_upper` field NAMES stay,
            // but they now carry the 95% CI AROUND the recall mean (single consumer is
            // the Memory RANGE band) instead of a Wilson CI on the mastered proportion.
            // `mastered_count`/`cards_with_data` remain the raw DATA-column counts.
            let (mastered_lower, mastered_upper) = mean_ci(&retrievabilities, WILSON_Z_95);
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
        use anki_proto::speedrun::ScoreScale;
        use anki_proto::speedrun::TopicScaffold;
        use anki_proto::speedrun::UnlockRequirement;

        use crate::speedrun::conformal_margin;
        use crate::speedrun::equate_linear;
        use crate::speedrun::exam_topic_weights;
        use crate::speedrun::scoring_config_from_profile;
        use crate::speedrun::weighted_ability;
        use crate::speedrun::wilson_interval;
        use crate::speedrun::WILSON_Z_95;

        let profile_json = self.speedrun_exam_profile_json("gre_math");
        let cfg = scoring_config_from_profile(&profile_json);
        let weights = exam_topic_weights(&profile_json);

        let timing = self.timing_today()?;
        let fsrs = FSRS::new(None).unwrap();

        let abstain_unit = || ScoreScaffold {
            point: 0.0,
            lower: 0.0,
            upper: 1.0,
            abstained: true,
            percentile: 0.0,
            scale: ScoreScale::Unit as i32,
            last_updated: 0,
        };
        let abstain_scaled = || ScoreScaffold {
            point: 0.0,
            lower: 0.0,
            upper: 0.0,
            abstained: true,
            percentile: 0.0,
            scale: ScoreScale::Gre200990 as i32,
            last_updated: 0,
        };

        let total = input.topics.len() as u32;
        let mut topics_out = Vec::with_capacity(input.topics.len());
        // (weight, performance point) for topics with a real Performance number.
        let mut ability_terms: Vec<(f64, f64)> = Vec::new();
        let mut total_attempts = 0u32;
        let mut covered = 0u32;
        let mut any_real = false;
        let mut overall_newest_secs = 0i64;

        for topic in &input.topics {
            let (recall_n, recall) = self.topic_recall(topic, &timing, &fsrs)?;
            let (attempts, correct, newest_ms) = self.topic_problem_stats(topic)?;
            total_attempts += attempts;
            overall_newest_secs = overall_newest_secs.max(newest_ms / 1000);
            // Coverage must be PROBLEM-based (PRD): a topic only counts once it has
            // enough timed problem attempts to yield a real Performance number. Using
            // the same threshold as the Performance block below so "covered" ==
            // "has a Performance score". Declarative flashcard study alone (recall_n)
            // does NOT count — memory != timed problem-solving.
            if attempts >= cfg.performance.min_problem_attempts {
                covered += 1;
            }
            let weight = weights.get(topic).copied().unwrap_or(0.0);

            // Performance = demonstrated problem accuracy (Wilson), only once
            // enough problems attempted; otherwise abstain (memory != application).
            let performance = if attempts >= cfg.performance.min_problem_attempts {
                let acc = correct as f64 / attempts as f64;
                let (lo, hi) = wilson_interval(correct, attempts, WILSON_Z_95);
                any_real = true;
                if weight > 0.0 {
                    ability_terms.push((weight, acc));
                }
                ScoreScaffold {
                    point: acc,
                    lower: lo,
                    upper: hi,
                    abstained: false,
                    percentile: 0.0,
                    scale: ScoreScale::Unit as i32,
                    last_updated: newest_ms / 1000,
                }
            } else {
                abstain_unit()
            };

            // §7d gap meter: declarative recall - problem accuracy (both present).
            let gap_delta = if recall_n > 0 && !performance.abstained {
                recall - performance.point
            } else {
                0.0
            };

            topics_out.push(TopicScaffold {
                topic: topic.clone(),
                performance: Some(performance),
                // Readiness is an exam-level score -> carried in overall_readiness.
                readiness: Some(abstain_scaled()),
                gap_delta,
            });
        }

        // ---- Overall readiness: flat IRT ability -> 200-990 + conformal + give-up
        // ----
        let mini_mocks = self.mini_mock_count(cfg.readiness.mini_mock_min_items)?;
        let coverage_frac = if total == 0 {
            0.0
        } else {
            covered as f64 / total as f64
        };
        let ability = weighted_ability(&ability_terms);
        let g = &cfg.readiness.give_up;

        let mut unlock: Vec<UnlockRequirement> = Vec::new();
        if mini_mocks < g.min_mini_mocks {
            unlock.push(UnlockRequirement {
                kind: "mini_mocks".into(),
                have: mini_mocks as f64,
                need: g.min_mini_mocks as f64,
                human: format!(
                    "Complete {} more timed mini-mock(s)",
                    g.min_mini_mocks - mini_mocks
                ),
                topic: String::new(),
            });
        }
        if coverage_frac < g.min_coverage {
            unlock.push(UnlockRequirement {
                kind: "coverage".into(),
                have: coverage_frac,
                need: g.min_coverage,
                human: format!(
                    "Cover more topics ({:.0}% now, need {:.0}%)",
                    coverage_frac * 100.0,
                    g.min_coverage * 100.0
                ),
                topic: String::new(),
            });
        }

        let (overall_readiness, abstain_reason) = if let Some(a) = ability {
            let e = &cfg.readiness.equating;
            let scaled = equate_linear(a, e.min_scaled, e.max_scaled);
            let margin = conformal_margin(
                cfg.readiness.conformal.base_margin,
                cfg.readiness.conformal.widen_k,
                total_attempts,
            );
            let width = 2.0 * margin;
            if width >= g.max_interval_width {
                unlock.push(UnlockRequirement {
                    kind: "interval_width".into(),
                    have: width,
                    need: g.max_interval_width,
                    human: "Answer more problems to narrow the estimate".into(),
                    topic: String::new(),
                });
            }
            // Give-up gate (all config-driven; NOT a min()-over-prereqs).
            let unlocked = mini_mocks >= g.min_mini_mocks
                && coverage_frac >= g.min_coverage
                && width < g.max_interval_width;
            if unlocked {
                let lo = (scaled - margin).clamp(e.min_scaled, e.max_scaled);
                let hi = (scaled + margin).clamp(e.min_scaled, e.max_scaled);
                (
                    ScoreScaffold {
                        point: scaled,
                        lower: lo,
                        upper: hi,
                        abstained: false,
                        // Percentile ABSTAINS: there is no ETS norm table available,
                        // and ability is not a percentile — emitting ability*100 here
                        // would be a fabricated number. 0.0 signals "no percentile";
                        // the UI does not display a %ile for readiness.
                        percentile: 0.0,
                        scale: ScoreScale::Gre200990 as i32,
                        last_updated: overall_newest_secs,
                    },
                    String::new(),
                )
            } else {
                (
                    abstain_scaled(),
                    "Readiness locked until the give-up rule is met".to_string(),
                )
            }
        } else {
            (abstain_scaled(), "No timed problem data yet".to_string())
        };

        Ok(anki_proto::speedrun::PerformanceReadinessResponse {
            scaffolding: !any_real,
            topics: topics_out,
            overall_readiness: Some(overall_readiness),
            abstain_reason,
            unlock_requirements: unlock,
        })
    }
}

impl Collection {
    /// Average FSRS retrievability of DECLARATIVE (non-problem) cards under a
    /// topic. Returns (cards_with_data, avg_recall). Batched: one search + one
    /// card scan. Read-only.
    fn topic_recall(
        &mut self,
        topic: &str,
        timing: &crate::scheduler::timing::SchedTimingToday,
        fsrs: &FSRS,
    ) -> error::Result<(u32, f64)> {
        let search = format!("(\"tag:{topic}\" OR \"tag:{topic}::*\") -\"tag:Speedrun::Problem\"");
        let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
        let mut rs: Vec<f64> = Vec::new();
        guard.col.storage.for_each_card_in_search(|card| {
            if let Some(state) = card.memory_state {
                let elapsed = card.seconds_since_last_review(timing).unwrap_or_default();
                let decay = card.decay.unwrap_or(FSRS5_DEFAULT_DECAY);
                rs.push(fsrs.current_retrievability_seconds(state.into(), elapsed, decay) as f64);
            }
            Ok(())
        })?;
        drop(guard);
        let n = rs.len() as u32;
        let avg = if n == 0 {
            0.0
        } else {
            rs.iter().sum::<f64>() / n as f64
        };
        Ok((n, avg))
    }

    /// Problem-card stats under a topic: (graded_attempts, correct, newest_ms).
    /// "correct" = button_chosen >= 3 (Good/Easy). Batched: one search + one
    /// revlog scan. Read-only.
    fn topic_problem_stats(&mut self, topic: &str) -> error::Result<(u32, u32, i64)> {
        let search = format!("(\"tag:{topic}\" OR \"tag:{topic}::*\") \"tag:Speedrun::Problem\"");
        let guard = self.search_cards_into_table(search.as_str(), SortMode::NoOrder)?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);
        let mut attempts = 0u32;
        let mut correct = 0u32;
        let mut newest = 0i64;
        for entry in &revlog {
            if entry.has_rating_and_affects_scheduling() {
                attempts += 1;
                if entry.button_chosen >= 3 {
                    correct += 1;
                }
                newest = newest.max(entry.id.0);
            }
        }
        Ok((attempts, correct, newest))
    }

    /// Count "timed mini-mocks": distinct epoch-days with >= `min_items` graded
    /// problem attempts (a proxy until Phase 3's real session mechanic).
    /// Read-only.
    fn mini_mock_count(&mut self, min_items: u32) -> error::Result<u32> {
        use std::collections::HashMap;
        let guard = self.search_cards_into_table("\"tag:Speedrun::Problem\"", SortMode::NoOrder)?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);
        let mut per_day: HashMap<i64, u32> = HashMap::new();
        for entry in &revlog {
            if entry.has_rating_and_affects_scheduling() {
                *per_day.entry(entry.id.0 / 86_400_000).or_default() += 1;
            }
        }
        Ok(per_day.values().filter(|c| **c >= min_items).count() as u32)
    }
}
