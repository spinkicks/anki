# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Regression tests for the Speedrun Home "START RUN" decision.

Guards the bug where due counts were read from ``col.decks.deck_tree`` (called
with ``now=0`` -> an all-zero *structural* tree) instead of
``col.sched.deck_due_tree`` (real due counts). With the buggy source, START RUN
always reported "all caught up" and never launched study.
"""

from __future__ import annotations

import os
import tempfile

from anki.collection import Collection
from anki.decks import DeckId
from aqt.speedrun_logic import decide_start_run

EXAM_DECK = "Speedrun::GRE Math"


def _empty_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def _add_new_card(col: Collection, deck_id: DeckId) -> None:
    # models.current() also materialises the stock notetypes on a fresh
    # collection; set fields by index so we don't depend on field names.
    notetype = col.models.current()
    note = col.new_note(notetype)
    note.fields[0] = "q"
    note.fields[1] = "a"
    col.add_note(note, deck_id)


def test_import_needed_when_deck_absent() -> None:
    col = _empty_col()
    try:
        decision = decide_start_run(col, EXAM_DECK)
        assert decision.status == "importNeeded"
    finally:
        col.close()


def test_caught_up_when_deck_present_but_empty() -> None:
    col = _empty_col()
    try:
        col.decks.id(EXAM_DECK)  # create the deck, add no cards
        decision = decide_start_run(col, EXAM_DECK)
        assert decision.status == "caughtUp"
        assert decision.new_left == 0
    finally:
        col.close()


def test_ready_when_cards_due() -> None:
    # THE regression: a freshly added new card in the exam deck IS due, so
    # START RUN must be "ready" (launch the reviewer) — not "caughtUp". With the
    # old col.decks.deck_tree() path this wrongly returned counts of 0.
    col = _empty_col()
    try:
        deck_id = col.decks.id(EXAM_DECK)
        _add_new_card(col, deck_id)
        decision = decide_start_run(col, EXAM_DECK)
        assert decision.status == "ready", f"expected ready, got {decision}"
        assert decision.deck_id == deck_id
    finally:
        col.close()


def test_scheduler_tree_has_counts_but_structural_tree_does_not() -> None:
    # Characterization test documenting WHY decide_start_run uses the scheduler.
    # col.decks.deck_tree() (now=0) yields ZERO counts; only
    # col.sched.deck_due_tree() computes real due counts. This is the exact
    # mechanism of the fixed bug; if Anki's behaviour ever changes here, the
    # helper's API choice can be revisited.
    col = _empty_col()
    try:
        deck_id = col.decks.id(EXAM_DECK)
        _add_new_card(col, deck_id)
        structural = col.decks.find_deck_in_tree(col.decks.deck_tree(), deck_id)
        scheduled = col.sched.deck_due_tree(deck_id)
        assert structural is not None and scheduled is not None
        assert structural.new_count == 0  # the bug: structural tree has no counts
        assert scheduled.new_count == 1  # the fix: scheduler computes real counts
    finally:
        col.close()
