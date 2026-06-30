# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun read-only analytics wrapper over the Rust SpeedrunService."""

from __future__ import annotations

import anki
import anki.collection
from anki import speedrun_pb2

# public export
CoverageResponse = speedrun_pb2.CoverageResponse


class SpeedrunManager:
    def __init__(self, col: anki.collection.Collection) -> None:
        self.col = col.weakref()

    def coverage(self, required_tags: list[str]) -> CoverageResponse:
        """How many of required_tags are present in the collection (prefix match),
        plus the engine version string."""
        return self.col._backend.get_coverage(required_tags=required_tags)
