# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun read-only analytics wrapper over the Rust SpeedrunService."""

from __future__ import annotations

from typing import cast

import anki
import anki.collection
from anki import speedrun_pb2
from anki.collection import OpChangesWithCount

# public export
CoverageResponse = speedrun_pb2.CoverageResponse
TopicMasteryResponse = speedrun_pb2.TopicMasteryResponse
ExamProfileResponse = speedrun_pb2.ExamProfileResponse
PerformanceReadinessResponse = speedrun_pb2.PerformanceReadinessResponse
CalibrationResponse = speedrun_pb2.CalibrationResponse


class SpeedrunManager:
    def __init__(self, col: anki.collection.Collection) -> None:
        self.col = col.weakref()

    def coverage(self, required_tags: list[str]) -> CoverageResponse:
        """How many of required_tags are present in the collection (prefix match),
        plus the engine version string."""
        return self.col._backend.get_coverage(required_tags=required_tags)

    def topic_mastery(
        self,
        topics: list[str],
        mastery_threshold: float = 0.9,
        min_reviews: int = 20,
    ) -> TopicMasteryResponse:
        """Per-topic FSRS memory aggregate: mastered proportion (Wilson 95%
        range), average recall, and an abstain flag when graded reviews are too
        few. Read-only. The dashboard/UI for this score is the desktop/TS
        layer's responsibility; this is the data seam."""
        return self.col._backend.get_topic_mastery(
            topics=topics,
            mastery_threshold=mastery_threshold,
            min_reviews=min_reviews,
        )

    def exam_profile(self, exam_id: str = "gre_math") -> ExamProfileResponse:
        """Read the exam-profile JSON stored in the synced collection config."""
        return self.col._backend.get_exam_profile(exam_id=exam_id)

    def set_exam_profile(self, profile_json: str, exam_id: str = "gre_math") -> None:
        """Store the exam-profile JSON in the synced collection config
        (uses the existing config API — a normal undoable config write)."""
        self.col.set_config(f"speedrun:exam_profile:{exam_id}", profile_json)

    def performance_readiness(self, topics: list[str]) -> PerformanceReadinessResponse:
        """Per-topic Performance (P(correct on a novel problem), from problem
        accuracy; abstains below the attempt threshold) + overall Readiness
        (flat-IRT 200-990 + conformal interval + config-driven give-up with
        unlock_requirements). Real, honest, non-AI numbers recomputed from synced
        collection data; abstains until there is enough data. Read-only."""
        return self.col._backend.get_performance_readiness(topics=topics)

    def calibration(
        self, topics: list[str], min_attempts: int = 20
    ) -> CalibrationResponse:
        """Calibration of the learner's SELF-RATED accuracy: Brier + ECE +
        reliability bins over logged pre-answer confidence (Sure/Think/Guess) on
        Speedrun::Problem attempts, scored against the self-graded outcome
        (button >= 3). Read-only; abstains below min_attempts (no fabricated
        numbers). NOT key-checked accuracy. Empty topics => all logged attempts."""
        return self.col._backend.get_calibration(
            topics=topics, min_attempts=min_attempts
        )

    def reorder_new(
        self,
        deck_id: int,
        topic_weights: dict[str, float],
        mode: int = 0,  # 0=FULL, 1=FEATURE_OFF, 2=PLAIN
    ) -> OpChangesWithCount:
        """Reposition new cards by points-at-stake + interleave (undoable).

        Mutating: writes persisted new-card positions only, never review
        due-dates or intervals. Goes through transact(Op::SortCards) so undo
        and integrity_check stay intact."""
        return self.col._backend.reorder_new_by_points_at_stake(
            deck_id=deck_id,
            # public API takes a plain int (0=FULL/1=FEATURE_OFF/2=PLAIN); the
            # generated backend types it as the AblationMode enum value.
            mode=cast("speedrun_pb2.AblationMode.V", mode),
            topic_weights=[
                speedrun_pb2.TopicWeight(topic=t, weight=w)
                for t, w in topic_weights.items()
            ],
        )
