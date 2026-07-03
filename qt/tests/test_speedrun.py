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


def test_decide_mini_mock_no_active_problems_when_all_suspended() -> None:
    # P2 FIX B: the Problems subdeck is PRESENT and holds problem cards, but every
    # one is suspended -> the mock search (deck:… -is:suspended) returns nothing.
    # This must be reported as "noActiveProblems" (unsuspend, not import), NOT the
    # dishonest "importNeeded" that used to conflate the two cases.
    col = _empty_col()
    try:
        deck_id = col.decks.id(PROBLEM_DECK)
        assert deck_id is not None
        _add_problem_card(col, deck_id)
        _add_problem_card(col, deck_id)
        # Suspend every card in the subdeck.
        cids = col.find_cards(f'deck:"{PROBLEM_DECK}"')
        assert cids, "fixture must have created problem cards"
        col.sched.suspend_cards(cids)
        assert not col.find_cards(f'deck:"{PROBLEM_DECK}" -is:suspended')

        decision = decide_mini_mock(col, PROBLEM_DECK)
        assert decision.status == "noActiveProblems", (
            f"expected noActiveProblems, got {decision}"
        )
        assert decision.deck_id is None
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


# ---- T6: desktop confidence capture (Qt-free parse/guard/reconcile) ----

from aqt import speedrun_capture  # noqa: E402


def _problem_notetype(col: Collection):
    """A note type literally named Speedrun::Problem (matches the seed model)."""
    mm = col.models
    # Materialise the stock note types first (a truly fresh collection has none
    # until something touches models); keeps the DB consistent.
    mm.current()
    nt = mm.new(speedrun_capture.PROBLEM_NOTETYPE)
    mm.add_field(nt, mm.new_field("Stem"))
    mm.add_field(nt, mm.new_field("Back"))
    tmpl = mm.new_template("Card 1")
    tmpl["qfmt"] = "{{Stem}}"
    tmpl["afmt"] = "{{FrontSide}}<hr>{{Back}}"
    mm.add_template(nt, tmpl)
    mm.add(nt)
    return nt


def _add_problem_note(col: Collection, deck_id: DeckId):
    nt = _problem_notetype(col)
    note = col.new_note(nt)
    note.fields[0] = "2+2?"
    note.tags = ["calc::single_var::integration", "Speedrun::Problem"]
    col.add_note(note, deck_id)
    return note.cards()[0]


def test_parse_conf_message_valid_and_invalid() -> None:
    assert speedrun_capture.parse_conf_message("speedrun:conf:sure") == "sure"
    assert speedrun_capture.parse_conf_message("speedrun:conf:THINK") == "think"
    assert speedrun_capture.parse_conf_message("speedrun:conf:guess") == "guess"
    # Not a conf command / unknown level => None (never silently mis-graded).
    assert speedrun_capture.parse_conf_message("minimock") is None
    assert speedrun_capture.parse_conf_message("speedrun:conf:bogus") is None
    assert speedrun_capture.parse_conf_message("speedrun:conf:") is None


def test_build_attempt_correct_is_self_rated_ease_ge_3() -> None:
    good = speedrun_capture.build_attempt(1, 100, "sure", ease=3, ts=5)
    assert good["correct"] is True and good["cid"] == 1 and good["revlog_id"] == 100
    easy = speedrun_capture.build_attempt(1, 101, "think", ease=4, ts=5)
    assert easy["correct"] is True
    hard = speedrun_capture.build_attempt(1, 102, "guess", ease=2, ts=5)
    assert hard["correct"] is False
    again = speedrun_capture.build_attempt(1, 103, "guess", ease=1, ts=5)
    assert again["correct"] is False


def _add_other_note(col: Collection, deck_id: DeckId):
    """A card whose note type is NOT Speedrun::Problem (a self-contained custom
    type, so the test doesn't depend on stock note types being materialised)."""
    mm = col.models
    mm.current()
    nt = mm.new("Speedrun::Declarative")
    mm.add_field(nt, mm.new_field("Front"))
    mm.add_field(nt, mm.new_field("Back"))
    tmpl = mm.new_template("Card 1")
    tmpl["qfmt"] = "{{Front}}"
    tmpl["afmt"] = "{{FrontSide}}<hr>{{Back}}"
    mm.add_template(nt, tmpl)
    mm.add(nt)
    note = col.new_note(nt)
    note.fields[0] = "q"
    col.add_note(note, deck_id)
    return note.cards()[0]


def test_is_problem_card_guards_note_type() -> None:
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_problem_note(col, did)
        assert speedrun_capture.is_problem_card(pcard)
        # A non-Problem note type is NOT captured.
        other = _add_other_note(col, did)
        assert not speedrun_capture.is_problem_card(other)
        assert not speedrun_capture.is_problem_card(None)
    finally:
        col.close()


def test_append_attempt_dedupes_by_cid_revlog() -> None:
    col = _empty_col()
    try:
        a = speedrun_capture.build_attempt(1, 100, "sure", ease=3, ts=0)
        speedrun_capture.append_attempt(col, a)
        speedrun_capture.append_attempt(col, a)  # duplicate key => ignored
        b = speedrun_capture.build_attempt(1, 101, "guess", ease=1, ts=0)
        speedrun_capture.append_attempt(col, b)
        log = col.get_config(speedrun_capture.CALIBRATION_LOG_KEY, [])
        assert len(log) == 2
        assert log[0]["level"] == "sure"
    finally:
        col.close()


# ---- T7: stale-stash clearing on bury/suspend/reviewer-close (BUG 5) ----


def test_clear_pending_removes_single_card() -> None:
    # BUG 5: a card-level suspend/bury must drop just that card's pending bet.
    speedrun_capture._pending.clear()
    speedrun_capture.stash_pending(1, "sure")
    speedrun_capture.stash_pending(2, "guess")
    speedrun_capture.clear_pending(1)
    assert 1 not in speedrun_capture._pending
    assert speedrun_capture._pending.get(2) == "guess"
    # Clearing an absent card is a harmless no-op.
    speedrun_capture.clear_pending(999)
    assert speedrun_capture._pending.get(2) == "guess"


def test_clear_all_pending_empties_dict() -> None:
    # BUG 5: closing the reviewer must drop every pending bet.
    speedrun_capture._pending.clear()
    speedrun_capture.stash_pending(1, "sure")
    speedrun_capture.stash_pending(2, "think")
    speedrun_capture.clear_all_pending()
    assert speedrun_capture._pending == {}


def test_clear_pending_for_note_clears_all_its_cards() -> None:
    # BUG 5: a note-level suspend/bury passes a NOTE id; every card of that note
    # (which is what _pending is keyed on) must be cleared.
    speedrun_capture._pending.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_problem_note(col, did)
        nid = pcard.nid
        speedrun_capture.stash_pending(pcard.id, "sure")
        # An unrelated card's pending must survive.
        speedrun_capture.stash_pending(pcard.id + 12345, "guess")
        speedrun_capture.clear_pending_for_note(col, nid)
        assert pcard.id not in speedrun_capture._pending
        assert speedrun_capture._pending.get(pcard.id + 12345) == "guess"
    finally:
        col.close()


def test_no_stale_attempt_after_suspend_then_later_answer() -> None:
    # BUG 5 (the whole point): press a confidence, suspend the card (which clears
    # the stash), then later answer that SAME card with no fresh press. No stale
    # attempt may be written for that new revlog id.
    speedrun_capture._pending.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_problem_note(col, did)
        cid = pcard.id
        # User presses "Sure" but then suspends instead of answering.
        speedrun_capture.stash_pending(cid, "sure")
        speedrun_capture.clear_pending(cid)  # what the suspend hook will do
        assert cid not in speedrun_capture._pending

        # The card comes back later and is answered WITHOUT a fresh press.
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)
        attempt = speedrun_capture.reconcile_answer(col, cid, ease=3)
        assert attempt is None  # no bet was made for THIS attempt
        log = col.get_config(speedrun_capture.CALIBRATION_LOG_KEY, [])
        assert log == []
    finally:
        col.close()


# ---- T8: pre-answer-only guard — no answer-side overwrite (BUG 6) ----


def test_is_question_state_guard() -> None:
    # BUG 6: only the QUESTION side may (re)stash a confidence.
    assert speedrun_capture.is_question_state("question") is True
    assert speedrun_capture.is_question_state("answer") is False
    assert speedrun_capture.is_question_state("transition") is False
    assert speedrun_capture.is_question_state(None) is False


def test_answer_side_press_does_not_overwrite_pre_answer_bet() -> None:
    # BUG 6: the Problem afmt re-renders the qfmt buttons ({{FrontSide}}), so a
    # post-reveal click must NOT overwrite the genuine pre-answer confidence.
    speedrun_capture._pending.clear()
    cid = 42
    # Pre-answer (question side): the bet is accepted.
    if speedrun_capture.is_question_state("question"):
        speedrun_capture.stash_pending(cid, "sure")
    assert speedrun_capture._pending.get(cid) == "sure"
    # Answer side: a "guess" click must be ignored, leaving "sure" intact.
    if speedrun_capture.is_question_state("answer"):
        speedrun_capture.stash_pending(cid, "guess")
    assert speedrun_capture._pending.get(cid) == "sure"


def test_reconcile_writes_attempt_after_answer() -> None:
    # Full desktop path: stash a confidence, answer the card (writes a revlog
    # row), reconcile => an attempt is logged with the answer's revlog id and the
    # self-rated outcome. No pending for a card => no write.
    speedrun_capture._pending.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_problem_note(col, did)
        cid = pcard.id
        # No pending => reconcile is a no-op.
        assert speedrun_capture.reconcile_answer(col, cid, ease=3) is None

        # Stash a confidence, then answer the card to produce a revlog row.
        speedrun_capture.stash_pending(cid, "sure")
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)  # Good => self-rated correct
        attempt = speedrun_capture.reconcile_answer(col, cid, ease=3)
        assert attempt is not None
        assert attempt["cid"] == cid
        assert attempt["level"] == "sure"
        assert attempt["correct"] is True
        # revlog id matches the newest revlog row for this card.
        newest = col.db.scalar(
            "SELECT id FROM revlog WHERE cid = ? ORDER BY id DESC LIMIT 1", cid
        )
        assert attempt["revlog_id"] == newest
        # Pending was consumed (a second reconcile writes nothing new).
        assert speedrun_capture.reconcile_answer(col, cid, ease=3) is None
        log = col.get_config(speedrun_capture.CALIBRATION_LOG_KEY, [])
        assert len(log) == 1
    finally:
        col.close()


# ---- T9: interactive MCQ auto-grade (BACKEND-authoritative key check) ----
#
# Thesis-critical: Performance must be OBJECTIVELY key-checked, not self-rated.
# A choice click fires pycmd("speedrun:mcq:<LETTER>"); the desktop hook stashes
# the chosen letter per card id, and on answer reads the card's note
# CorrectAnswer field to compute `correct` server-side (NEVER trusting a
# client-sent flag). The attempt is logged to speedrun:mcq_attempts, deduped by
# (cid, revlog_id) — a NEW key that does not touch speedrun:calibration_log.


def _add_mcq_note(col: Collection, deck_id: DeckId, correct_letter: str = "C"):
    """A Speedrun::Problem note that carries a CorrectAnswer field (the seed
    model has Stem/Choices/CorrectAnswer/...). The backend reconcile reads this
    field to key-check the chosen letter, so the fixture must expose it."""
    mm = col.models
    mm.current()
    nt = mm.new(speedrun_capture.PROBLEM_NOTETYPE)
    mm.add_field(nt, mm.new_field("Stem"))
    mm.add_field(nt, mm.new_field("Choices"))
    mm.add_field(nt, mm.new_field("CorrectAnswer"))
    tmpl = mm.new_template("Card 1")
    tmpl["qfmt"] = "{{Stem}}"
    tmpl["afmt"] = "{{FrontSide}}<hr>{{CorrectAnswer}}"
    mm.add_template(nt, tmpl)
    mm.add(nt)
    note = col.new_note(nt)
    note.fields[0] = "2+2?"
    note.fields[1] = "(A) 1\n(B) 2\n(C) 4\n(D) 5\n(E) 6"
    note.fields[2] = correct_letter
    note.tags = ["calc::single_var", "Speedrun::Problem"]
    col.add_note(note, deck_id)
    return note.cards()[0]


def test_parse_mcq_message_valid_and_invalid() -> None:
    assert speedrun_capture.parse_mcq_message("speedrun:mcq:A") == "A"
    assert speedrun_capture.parse_mcq_message("speedrun:mcq:e") == "E"  # normalised
    assert speedrun_capture.parse_mcq_message("speedrun:mcq: C ") == "C"  # trimmed
    # Not an mcq command / letter out of A-E => None (never fabricate a grade).
    assert speedrun_capture.parse_mcq_message("speedrun:conf:sure") is None
    assert speedrun_capture.parse_mcq_message("speedrun:mcq:F") is None
    assert speedrun_capture.parse_mcq_message("speedrun:mcq:") is None
    assert speedrun_capture.parse_mcq_message("speedrun:mcq:AB") is None


def test_build_mcq_attempt_shape_matches_frozen_contract() -> None:
    a = speedrun_capture.build_mcq_attempt(1, 100, "C", correct=True, ts=5)
    assert a == {
        "cid": 1,
        "revlog_id": 100,
        "chosen": "C",
        "correct": True,
        "ts": 5,
    }
    b = speedrun_capture.build_mcq_attempt(2, 200, "A", correct=False, ts=9)
    assert b["chosen"] == "A" and b["correct"] is False


def test_append_mcq_attempt_dedupes_by_cid_revlog_on_new_key() -> None:
    col = _empty_col()
    try:
        a = speedrun_capture.build_mcq_attempt(1, 100, "C", correct=True, ts=0)
        speedrun_capture.append_mcq_attempt(col, a)
        speedrun_capture.append_mcq_attempt(col, a)  # duplicate key => ignored
        b = speedrun_capture.build_mcq_attempt(1, 101, "A", correct=False, ts=0)
        speedrun_capture.append_mcq_attempt(col, b)
        log = col.get_config(speedrun_capture.MCQ_ATTEMPTS_KEY, [])
        assert len(log) == 2
        assert log[0]["chosen"] == "C"
        # The MCQ log is a NEW key and must not pollute the calibration log.
        assert col.get_config(speedrun_capture.CALIBRATION_LOG_KEY, []) == []
    finally:
        col.close()


def test_reconcile_mcq_computes_correct_from_note_correct_answer() -> None:
    # Backend-authoritative grade: a matching pick => correct True; a mismatching
    # pick => False. The grade is read from the note's CorrectAnswer field, NOT
    # from any client-sent flag.
    speedrun_capture._pending_mcq.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_mcq_note(col, did, correct_letter="C")
        cid = pcard.id
        speedrun_capture.stash_pending_mcq(cid, "C")  # user picked the right one
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)
        attempt = speedrun_capture.reconcile_mcq(col, cid)
        assert attempt is not None
        assert attempt["cid"] == cid
        assert attempt["chosen"] == "C"
        assert attempt["correct"] is True
        newest = col.db.scalar(
            "SELECT id FROM revlog WHERE cid = ? ORDER BY id DESC LIMIT 1", cid
        )
        assert attempt["revlog_id"] == newest
        # Consumed: a second reconcile writes nothing new.
        assert speedrun_capture.reconcile_mcq(col, cid) is None
        log = col.get_config(speedrun_capture.MCQ_ATTEMPTS_KEY, [])
        assert len(log) == 1
    finally:
        col.close()


def test_reconcile_mcq_wrong_pick_is_graded_incorrect() -> None:
    speedrun_capture._pending_mcq.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_mcq_note(col, did, correct_letter="C")
        cid = pcard.id
        speedrun_capture.stash_pending_mcq(cid, "A")  # user picked wrong
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)  # even a Good self-rate can't fake it
        attempt = speedrun_capture.reconcile_mcq(col, cid)
        assert attempt is not None
        assert attempt["chosen"] == "A"
        assert attempt["correct"] is False
    finally:
        col.close()


def test_reconcile_mcq_no_pick_writes_nothing() -> None:
    # No MCQ click before answering => no MCQ attempt is written (the review
    # falls back to self-rated calibration only; we never fabricate a grade).
    speedrun_capture._pending_mcq.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_mcq_note(col, did, correct_letter="C")
        cid = pcard.id
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)
        assert speedrun_capture.reconcile_mcq(col, cid) is None
        assert col.get_config(speedrun_capture.MCQ_ATTEMPTS_KEY, []) == []
    finally:
        col.close()


def test_clear_pending_mcq_removes_single_card() -> None:
    speedrun_capture._pending_mcq.clear()
    speedrun_capture.stash_pending_mcq(1, "A")
    speedrun_capture.stash_pending_mcq(2, "B")
    speedrun_capture.clear_pending_mcq(1)
    assert 1 not in speedrun_capture._pending_mcq
    assert speedrun_capture._pending_mcq.get(2) == "B"
    speedrun_capture.clear_pending_mcq(999)  # absent => no-op
    assert speedrun_capture._pending_mcq.get(2) == "B"


def test_clear_all_pending_mcq_empties_dict() -> None:
    speedrun_capture._pending_mcq.clear()
    speedrun_capture.stash_pending_mcq(1, "A")
    speedrun_capture.stash_pending_mcq(2, "C")
    speedrun_capture.clear_all_pending_mcq()
    assert speedrun_capture._pending_mcq == {}


def test_clear_pending_mcq_for_note_clears_all_its_cards() -> None:
    speedrun_capture._pending_mcq.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_mcq_note(col, did)
        nid = pcard.nid
        speedrun_capture.stash_pending_mcq(pcard.id, "C")
        speedrun_capture.stash_pending_mcq(pcard.id + 12345, "A")  # unrelated card
        speedrun_capture.clear_pending_mcq_for_note(col, nid)
        assert pcard.id not in speedrun_capture._pending_mcq
        assert speedrun_capture._pending_mcq.get(pcard.id + 12345) == "A"
    finally:
        col.close()


def test_no_stale_mcq_attempt_after_suspend_then_later_answer() -> None:
    # Suspend clears the MCQ stash, so a later answer with no fresh pick logs
    # nothing (no fabricated key-check for a choice the user never made).
    speedrun_capture._pending_mcq.clear()
    col = _empty_col()
    try:
        did = col.decks.get_current_id()
        pcard = _add_mcq_note(col, did, correct_letter="C")
        cid = pcard.id
        speedrun_capture.stash_pending_mcq(cid, "C")
        speedrun_capture.clear_pending_mcq(cid)  # what the suspend hook does
        assert cid not in speedrun_capture._pending_mcq
        card = col.sched.getCard()
        assert card is not None and card.id == cid
        col.sched.answerCard(card, 3)
        assert speedrun_capture.reconcile_mcq(col, cid) is None
        assert col.get_config(speedrun_capture.MCQ_ATTEMPTS_KEY, []) == []
    finally:
        col.close()


def test_mcq_answer_side_press_does_not_overwrite_pre_answer_pick() -> None:
    # The Problem afmt re-renders the qfmt via {{FrontSide}}, so a post-reveal
    # choice click must NOT overwrite the genuine question-side pick. The
    # question-state guard is shared with the LS1 confidence path.
    speedrun_capture._pending_mcq.clear()
    cid = 42
    if speedrun_capture.is_question_state("question"):
        speedrun_capture.stash_pending_mcq(cid, "C")
    assert speedrun_capture._pending_mcq.get(cid) == "C"
    if speedrun_capture.is_question_state("answer"):
        speedrun_capture.stash_pending_mcq(cid, "A")
    assert speedrun_capture._pending_mcq.get(cid) == "C"
