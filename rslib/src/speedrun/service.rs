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
        // Full mode has NO meaningful ordering signal when there are no positive
        // topic weights: interleave_by_topic would round-robin zero usable
        // buckets, so every card falls to the "unmatched" tail in note order —
        // churning positions for no benefit. Treat that like Plain (empty op).
        // NOTE: this guard is Full-only ON PURPOSE. FeatureOff is the ablation
        // BASELINE whose ordering signal is note-id, not weights, so it must
        // still produce its note-id reposition even with empty/zero weights.
        if mode == AblationMode::Full
            && (topic_weights.is_empty() || topic_weights.iter().all(|(_, w)| *w <= 0.0))
        {
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
                // Unique note ids in card-encounter order (interleave_by_topic is
                // stable within a bucket, so this order is observable and must be
                // preserved). Was an N+1 (one get_note per note); now a SINGLE
                // batched tag fetch (mirrors get_topic_mastery's batch pattern):
                // one query for all tags, then map each unique note to its topic.
                let mut unique_nids: Vec<NoteId> = Vec::new();
                let mut seen = std::collections::HashSet::new();
                for c in &cards {
                    if seen.insert(c.note_id) {
                        unique_nids.push(c.note_id);
                    }
                }
                let tags_by_nid: std::collections::HashMap<NoteId, Vec<String>> = col
                    .storage
                    .get_note_tags_by_id_list(&unique_nids)?
                    .into_iter()
                    .map(|nt| {
                        (
                            nt.id,
                            crate::tags::split_tags(&nt.tags)
                                .map(str::to_string)
                                .collect(),
                        )
                    })
                    .collect();
                let note_topic: Vec<(i64, Option<usize>)> = unique_nids
                    .iter()
                    .map(|nid| {
                        let empty: Vec<String> = Vec::new();
                        let tags = tags_by_nid.get(nid).unwrap_or(&empty);
                        (
                            nid.0,
                            crate::speedrun::topic_index_for_tags(tags, &topic_weights),
                        )
                    })
                    .collect();
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

    /// Read all logged calibration attempts (config-blob), deduped by
    /// (cid, revlog_id). Missing/invalid key => empty. Read-only.
    pub(crate) fn speedrun_read_calibration_attempts(
        &self,
    ) -> Vec<crate::speedrun::CalibrationAttempt> {
        let raw: Vec<crate::speedrun::CalibrationAttempt> = self
            .get_config_optional(crate::speedrun::CALIBRATION_LOG_CONFIG_KEY)
            .unwrap_or_default();
        crate::speedrun::dedupe_attempts(raw)
    }

    /// Append one calibration attempt to the config-blob log, deduped by
    /// (cid, revlog_id). Light Speedrun-owned config mutation (mirrors the
    /// other `speedrun:*` config writes); NOT undoable and touches no
    /// cards/notes/ scheduling. A repeated (cid, revlog_id) is a no-op
    /// (idempotent capture).
    ///
    /// The desktop MVP capture path writes the SAME blob from Python via
    /// `col.set_config` (a plain `speedrun:*` config write; see
    /// `aqt/speedrun_capture.py`), so this Rust twin is currently exercised
    /// only by the store round-trip tests. Kept as the canonical Rust store
    /// API for a future engine-side writer (Android capture, batch import).
    #[allow(dead_code)]
    pub(crate) fn speedrun_append_calibration_attempt(
        &mut self,
        attempt: crate::speedrun::CalibrationAttempt,
    ) -> Result<()> {
        let mut log: Vec<crate::speedrun::CalibrationAttempt> = self
            .get_config_optional(crate::speedrun::CALIBRATION_LOG_CONFIG_KEY)
            .unwrap_or_default();
        if log
            .iter()
            .any(|a| a.cid == attempt.cid && a.revlog_id == attempt.revlog_id)
        {
            return Ok(());
        }
        log.push(attempt);
        self.set_config_json(crate::speedrun::CALIBRATION_LOG_CONFIG_KEY, &log, false)?;
        Ok(())
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

    fn get_calibration(
        &mut self,
        input: anki_proto::speedrun::GetCalibrationRequest,
    ) -> error::Result<anki_proto::speedrun::CalibrationResponse> {
        use anki_proto::speedrun::ReliabilityBin;

        use crate::speedrun::brier_score;
        use crate::speedrun::confidence_to_prob;
        use crate::speedrun::ece;
        use crate::speedrun::reliability_bins;
        use crate::speedrun::MIN_REVIEWS_DEFAULT;

        let min_attempts = if input.min_attempts == 0 {
            MIN_REVIEWS_DEFAULT
        } else {
            input.min_attempts
        };

        // Read the deduped attempt log, then optionally scope to the requested
        // topics (empty => all attempts). Topic scoping matches an attempt's card
        // to the requested topics by the same prefix rule as topic_problem_stats.
        let mut attempts = self.speedrun_read_calibration_attempts();
        if !input.topics.is_empty() {
            let allowed = self.speedrun_calibration_cids_for_topics(&input.topics)?;
            attempts.retain(|a| allowed.contains(&a.cid));
        }

        let backend_version = crate::version::version().to_string();

        // Honest abstain: below the threshold we emit NO numbers (all zero) and
        // no bins — the UI shows "— abstains", never a fabricated Brier/ECE.
        if (attempts.len() as u32) < min_attempts {
            return Ok(anki_proto::speedrun::CalibrationResponse {
                brier: 0.0,
                ece: 0.0,
                attempts: attempts.len() as u32,
                abstained: true,
                backend_version,
                bins: Vec::new(),
            });
        }

        // (forecast_prob, outcome) pairs. Outcome is the SELF-RATED correctness
        // (button >= 3, captured at answer time), NOT key-checked accuracy.
        let pairs: Vec<(f64, u8)> = attempts
            .iter()
            .map(|a| (confidence_to_prob(&a.level), a.correct as u8))
            .collect();

        let bins = reliability_bins(&pairs)
            .into_iter()
            .map(|(confidence, accuracy, n)| ReliabilityBin {
                confidence,
                accuracy,
                n,
            })
            .collect();

        Ok(anki_proto::speedrun::CalibrationResponse {
            brier: brier_score(&pairs),
            ece: ece(&pairs),
            attempts: attempts.len() as u32,
            abstained: false,
            backend_version,
            bins,
        })
    }
}

impl Collection {
    /// Set of card ids under any of `topics` (prefix rule) that are
    /// Speedrun::Problem cards — used to scope the calibration attempt log to a
    /// topic selection. Read-only.
    fn speedrun_calibration_cids_for_topics(
        &mut self,
        topics: &[String],
    ) -> error::Result<std::collections::HashSet<i64>> {
        let mut cids = std::collections::HashSet::new();
        for topic in topics {
            let search =
                format!("(\"tag:{topic}\" OR \"tag:{topic}::*\") \"tag:Speedrun::Problem\"");
            for cid in self.search_cards(search.as_str(), SortMode::NoOrder)? {
                cids.insert(cid.0);
            }
        }
        Ok(cids)
    }

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

    /// Count "timed mini-mocks" as SESSIONS, not calendar days. A session is a
    /// run of graded problem-attempt revlog entries with no gap of at least
    /// `SESSION_GAP_MS` between consecutive attempts; a session counts toward
    /// the total once it holds at least `min_items` attempts. This fixes
    /// the day-proxy bug where two separate mini-mocks on the SAME day
    /// counted as one, under-counting the readiness give-up gate
    /// (`min_mini_mocks`). Read-only.
    fn mini_mock_count(&mut self, min_items: u32) -> error::Result<u32> {
        let guard = self.search_cards_into_table("\"tag:Speedrun::Problem\"", SortMode::NoOrder)?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);
        // Collect the graded problem-attempt timestamps (epoch-ms revlog ids).
        let mut times: Vec<i64> = revlog
            .iter()
            .filter(|e| e.has_rating_and_affects_scheduling())
            .map(|e| e.id.0)
            .collect();
        Ok(crate::speedrun::count_mock_sessions(&mut times, min_items))
    }
}
