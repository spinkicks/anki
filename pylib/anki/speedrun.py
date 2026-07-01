# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun read-only analytics wrapper over the Rust SpeedrunService."""

from __future__ import annotations

import anki
import anki.collection
from anki import speedrun_pb2

# public export
CoverageResponse = speedrun_pb2.CoverageResponse
TopicMasteryResponse = speedrun_pb2.TopicMasteryResponse


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
