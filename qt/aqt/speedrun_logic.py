# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Pure, Qt-free decision logic for the Speedrun Home "START RUN" button.

Kept separate from the Qt dialog (``speedrun.py``) so it can be unit-tested with
a real ``Collection`` and no ``QApplication``.

The whole point of this module is the scheduler API choice. Due counts MUST come
from ``col.sched.deck_due_tree`` (which calls the backend with ``now=int_time``
so counts are computed for *today*), NOT ``col.decks.deck_tree`` (which passes
``now=0`` — the backend then returns a purely *structural* tree whose
new/review/learn counts are all ZERO). Reading counts off the structural tree
made START RUN always report "all caught up", so it never launched study. This
module is the single place that decision is made, and the regression tests in
``qt/tests/test_speedrun.py`` pin the correct behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.decks import DeckId


class StartRunDecision(NamedTuple):
    # "importNeeded": exam deck absent      -> prompt the user to import it
    # "caughtUp":     deck present, 0 due   -> honest banner (+ Custom Study)
    # "ready":        cards due             -> launch the reviewer on `deck_id`
    status: Literal["importNeeded", "caughtUp", "ready"]
    # New cards remaining today; only meaningful for "caughtUp" (else 0).
    new_left: int = 0
    # Resolved exam deck id; only set for "ready" (else None).
    deck_id: DeckId | None = None


def decide_start_run(col: Collection, exam_deck_name: str) -> StartRunDecision:
    """Decide, honestly, what START RUN should do for ``exam_deck_name``.

    Counts come from the scheduler's due tree so they reflect what is actually
    due right now (see the module docstring for why this matters).
    """
    deck_id = col.decks.id_for_name(exam_deck_name)
    if deck_id is None:
        return StartRunDecision("importNeeded")
    node = col.sched.deck_due_tree(deck_id)
    if node is None:
        return StartRunDecision("caughtUp")
    due = node.new_count + node.review_count + node.learn_count
    if due == 0:
        return StartRunDecision("caughtUp", new_left=node.new_count)
    return StartRunDecision("ready", deck_id=deck_id)
