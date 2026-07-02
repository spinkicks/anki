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
from aqt.speedrun_logic import (
    build_mini_mock_deck,
    decide_mini_mock,
    decide_start_run,
)

EXAM_DECK = "Speedrun::GRE Math"
PROBLEM_DECK = "Speedrun::GRE Math::Problems"
MINI_MOCK_DECK = "Speedrun Mini-Mock"


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


def _add_problem_card(col: Collection, deck_id: DeckId) -> None:
    # A "problem" for the mini-mock is just a normal note living in the Problems
    # subdeck and tagged Speedrun::Problem (the real bank uses a dedicated
    # notetype, but decide/build only care about deck membership + suspension,
    # so a stock note in the right deck is a faithful fixture).
    notetype = col.models.current()
    note = col.new_note(notetype)
    note.fields[0] = "q"
    note.fields[1] = "a"
    note.tags.append("Speedrun::Problem")
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


def test_decide_mini_mock_import_needed() -> None:
    # No Problems subdeck at all -> the bank hasn't been imported yet.
    col = _empty_col()
    try:
        decision = decide_mini_mock(col, PROBLEM_DECK)
        assert decision.status == "importNeeded"
    finally:
        col.close()


def test_decide_mini_mock_ready() -> None:
    # Problems subdeck with a couple of non-suspended problem cards -> ready.
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        _add_problem_card(col, deck_id)
        _add_problem_card(col, deck_id)
        decision = decide_mini_mock(col, PROBLEM_DECK)
        assert decision.status == "ready", f"expected ready, got {decision}"
        assert decision.deck_id == deck_id
    finally:
        col.close()


def test_build_mini_mock_deck() -> None:
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        for _ in range(3):
            _add_problem_card(col, deck_id)

        did = build_mini_mock_deck(col, PROBLEM_DECK, 2)
        assert did

        # The filtered deck must reschedule=True so mock attempts feed the
        # engine's Performance score + the Readiness give-up counter (which both
        # exclude is_cramming()/reschedule=false reviews).
        deck = col.sched.get_or_create_filtered_deck(did)
        assert deck.config.reschedule is True
        assert len(deck.config.search_terms) == 1
        term = deck.config.search_terms[0]
        # The backend normalises quoting (it may re-quote a whole term that
        # contains spaces), so assert on the semantic pieces, not exact quotes.
        assert "deck:" in term.search
        assert "Speedrun::GRE Math::Problems" in term.search
        assert "-is:suspended" in term.search
        assert term.limit == 2

        # Only up to `size` problem cards get pulled into the filtered deck, and
        # the search really targets the Problems deck (3 cards exist; limit=2).
        held = col.find_cards(f'deck:"{MINI_MOCK_DECK}"')
        assert 0 < len(held) <= 2
    finally:
        col.close()


def test_build_mini_mock_deck_size_zero_clamps_and_builds() -> None:
    # Regression (P2 FIX A): a config mini_mock_size of 0 used to reach the
    # filtered-deck build as limit=0, which pulls zero cards and makes Anki raise
    # FilteredDeckError (SearchReturnedNoCards) -> the mini-mock launch crashed.
    # build_mini_mock_deck must clamp size to a >=1 floor so a real deck builds.
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        for _ in range(3):
            _add_problem_card(col, deck_id)

        # Must NOT raise, and must produce a usable filtered deck.
        did = build_mini_mock_deck(col, PROBLEM_DECK, 0)
        assert did

        deck = col.sched.get_or_create_filtered_deck(did)
        term = deck.config.search_terms[0]
        assert term.limit >= 1, f"size 0 must clamp to >=1, got {term.limit}"
        held = col.find_cards(f'deck:"{MINI_MOCK_DECK}"')
        assert len(held) >= 1, "clamped mini-mock must hold at least one card"
    finally:
        col.close()


def test_build_mini_mock_deck_negative_size_clamps_and_builds() -> None:
    # A negative config value (also invalid) must clamp the same way and build.
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        for _ in range(3):
            _add_problem_card(col, deck_id)

        did = build_mini_mock_deck(col, PROBLEM_DECK, -5)
        assert did
        deck = col.sched.get_or_create_filtered_deck(did)
        assert deck.config.search_terms[0].limit >= 1
    finally:
        col.close()


def test_build_mini_mock_deck_reuses_existing_no_orphans() -> None:
    # Regression: building the mini-mock deck twice must reuse the SAME filtered
    # deck (resolve-by-name then update in place), not create a second deck that
    # Anki auto-suffixes ("Speedrun Mini-Mock+", "++", …) and orphans, stranding
    # cards. After two builds exactly ONE "Speedrun Mini-Mock*" deck may exist.
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        for _ in range(3):
            _add_problem_card(col, deck_id)

        first = build_mini_mock_deck(col, PROBLEM_DECK, 2)
        second = build_mini_mock_deck(col, PROBLEM_DECK, 2)
        # Same deck reused, not a fresh suffixed one.
        assert first == second

        mock_decks = [
            d
            for d in col.decks.all_names_and_ids()
            if d.name.startswith(MINI_MOCK_DECK)
        ]
        assert len(mock_decks) == 1, (
            "exactly one Mini-Mock deck (no '+'/'++' orphans), "
            f"got {[d.name for d in mock_decks]}"
        )
        assert mock_decks[0].name == MINI_MOCK_DECK

        # Still a filtered deck with reschedule=True after the in-place update.
        deck = col.sched.get_or_create_filtered_deck(DeckId(mock_decks[0].id))
        assert deck.config.reschedule is True
    finally:
        col.close()
