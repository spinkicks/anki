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
    SEED_APKG_NAME,
    build_mini_mock_deck,
    decide_mini_mock,
    decide_start_run,
    maybe_import_seed_deck,
    resolve_mini_mock_size,
    speedrun_seed_apkg_path,
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


# ---- P2-b: defensive mini-mock size resolution from (possibly bad) config ----
#
# _start_mini_mock read the size as int(col.get_config("speedrun:mini_mock_size",
# 10)). get_config's default only fires when the key is ABSENT; a PRESENT JSON
# null / non-numeric string / decimal string makes int(...) raise BEFORE the
# clamp, with no surrounding guard -> the mini-mock launch crashes. A synced
# collection can carry such a value. resolve_mini_mock_size must coerce
# defensively (fall back to the default), THEN clamp — never raise.


def test_resolve_mini_mock_size_absent_key_uses_default() -> None:
    col = _empty_col()
    try:
        # Key never set -> the default flows through and clamps to itself.
        assert resolve_mini_mock_size(col, default=10) == 10
    finally:
        col.close()


def test_resolve_mini_mock_size_null_config_falls_back_to_default() -> None:
    # A PRESENT JSON null (not absent) previously reached int(None) -> TypeError.
    col = _empty_col()
    try:
        col.set_config("speedrun:mini_mock_size", None)
        assert resolve_mini_mock_size(col, default=10) == 10
    finally:
        col.close()


def test_resolve_mini_mock_size_non_numeric_string_falls_back() -> None:
    # A non-numeric string previously reached int("abc") -> ValueError.
    col = _empty_col()
    try:
        col.set_config("speedrun:mini_mock_size", "abc")
        assert resolve_mini_mock_size(col, default=10) == 10
    finally:
        col.close()


def test_resolve_mini_mock_size_decimal_string_falls_back() -> None:
    # A decimal string ("7.5") is also not int-parseable -> fall back, don't crash.
    col = _empty_col()
    try:
        col.set_config("speedrun:mini_mock_size", "7.5")
        assert resolve_mini_mock_size(col, default=10) == 10
    finally:
        col.close()


def test_resolve_mini_mock_size_valid_value_is_clamped() -> None:
    # A valid numeric config value flows through the clamp (still >=1, <=cap).
    col = _empty_col()
    try:
        col.set_config("speedrun:mini_mock_size", 3)
        assert resolve_mini_mock_size(col, default=10) == 3
        # Numeric string that IS int-parseable is honoured too.
        col.set_config("speedrun:mini_mock_size", "5")
        assert resolve_mini_mock_size(col, default=10) == 5
        # Out-of-range valid ints still clamp (0 -> floor 1).
        col.set_config("speedrun:mini_mock_size", 0)
        assert resolve_mini_mock_size(col, default=10) == 1
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


# ---- Installer seed-deck auto-import (Qt-free decision + idempotent import) ----
#
# The desktop installer ships gre_math_seed.apkg inside the packaged app so a
# grader who installs the MSI has the deck already loaded — zero manual import.
# The first-run hook (main.py, mirroring the auto-open hook: post-sync, inside
# the `not safeMode` guard) calls maybe_import_seed_deck. These tests pin the
# Qt-free logic: import only when the exam deck is ABSENT and the apkg EXISTS;
# never re-import (idempotent); never crash on a missing/invalid apkg.

from anki.collection import DeckIdLimit, ExportAnkiPackageOptions  # noqa: E402


def _make_seed_apkg(path: str) -> None:
    """Build a fixture .apkg holding the exam deck + one card, like the real seed.

    Faithful to the shipped seed: a real .apkg (round-trippable by the same
    import API) whose top-level deck is literally "Speedrun::GRE Math".
    """
    src = _empty_col()
    try:
        deck_id = src.decks.id(EXAM_DECK)
        assert deck_id is not None
        _add_new_card(src, deck_id)
        src.export_anki_package(
            out_path=path,
            options=ExportAnkiPackageOptions(
                with_scheduling=False,
                with_deck_configs=False,
                legacy=False,
            ),
            limit=DeckIdLimit(deck_id=deck_id),
        )
    finally:
        src.close()


def test_maybe_import_seed_deck_imports_when_deck_absent() -> None:
    # Fresh collection, no exam deck, bundled apkg present -> import runs and the
    # deck (with its card) appears. This is the grader's zero-import first run.
    apkg = tempfile.mktemp(suffix=".apkg")
    _make_seed_apkg(apkg)
    col = _empty_col()
    try:
        assert col.decks.id_for_name(EXAM_DECK) is None
        imported = maybe_import_seed_deck(col, EXAM_DECK, apkg)
        assert imported is True
        assert col.decks.id_for_name(EXAM_DECK) is not None
        # The card came in with the deck.
        assert col.find_cards(f'deck:"{EXAM_DECK}"')
    finally:
        col.close()
        os.unlink(apkg)


def test_maybe_import_seed_deck_skips_when_deck_present() -> None:
    # Idempotency: the exam deck already exists -> SKIP. No import, no duplicate.
    apkg = tempfile.mktemp(suffix=".apkg")
    _make_seed_apkg(apkg)
    col = _empty_col()
    try:
        # Pre-create the exam deck so the guard trips.
        col.decks.id(EXAM_DECK)
        before = len(col.decks.all_names_and_ids())
        imported = maybe_import_seed_deck(col, EXAM_DECK, apkg)
        assert imported is False
        after = len(col.decks.all_names_and_ids())
        assert after == before, "import must not have added/duplicated decks"
    finally:
        col.close()
        os.unlink(apkg)


def test_maybe_import_seed_deck_idempotent_runs_twice_imports_once() -> None:
    # Running the hook twice must import exactly once: the second call sees the
    # now-present deck and skips (no dup notes/cards).
    apkg = tempfile.mktemp(suffix=".apkg")
    _make_seed_apkg(apkg)
    col = _empty_col()
    try:
        assert maybe_import_seed_deck(col, EXAM_DECK, apkg) is True
        cards_after_first = len(col.find_cards(f'deck:"{EXAM_DECK}"'))
        assert cards_after_first >= 1

        assert maybe_import_seed_deck(col, EXAM_DECK, apkg) is False
        cards_after_second = len(col.find_cards(f'deck:"{EXAM_DECK}"'))
        assert cards_after_second == cards_after_first, "must not re-import"
    finally:
        col.close()
        os.unlink(apkg)


def test_maybe_import_seed_deck_missing_apkg_is_noop_no_crash() -> None:
    # No bundled apkg found (apkg_path is None) -> no-op, no crash, deck stays absent.
    col = _empty_col()
    try:
        imported = maybe_import_seed_deck(col, EXAM_DECK, None)
        assert imported is False
        assert col.decks.id_for_name(EXAM_DECK) is None
    finally:
        col.close()


def test_maybe_import_seed_deck_nonexistent_path_is_noop_no_crash() -> None:
    # A path that points nowhere (packaged file somehow absent) must degrade to a
    # no-op, never raise into the launch sequence.
    col = _empty_col()
    try:
        bogus = tempfile.mktemp(suffix=".apkg")  # never created
        assert not os.path.exists(bogus)
        imported = maybe_import_seed_deck(col, EXAM_DECK, bogus)
        assert imported is False
        assert col.decks.id_for_name(EXAM_DECK) is None
    finally:
        col.close()


def test_maybe_import_seed_deck_invalid_apkg_is_noop_no_crash() -> None:
    # A corrupt/non-apkg file at the path must NOT crash the launch: the import
    # error is swallowed and the function reports False.
    col = _empty_col()
    bad = tempfile.mktemp(suffix=".apkg")
    with open(bad, "wb") as f:
        f.write(b"this is not a zip/apkg")
    try:
        imported = maybe_import_seed_deck(col, EXAM_DECK, bad)
        assert imported is False
        assert col.decks.id_for_name(EXAM_DECK) is None
    finally:
        col.close()
        os.unlink(bad)


def test_speedrun_seed_apkg_path_resolves_packaged_first(tmp_path, monkeypatch) -> None:
    # Resolution order: the packaged resource dir (aqt_data_path()) wins; only if
    # it's absent do we fall back to the dev repo path. Here the packaged file
    # exists, so it must be returned.
    import aqt.speedrun_logic as sl

    packaged = tmp_path / "pkgdata"
    packaged.mkdir()
    seed = packaged / SEED_APKG_NAME
    seed.write_bytes(b"x")
    monkeypatch.setattr(sl, "_aqt_data_dir", lambda: packaged)

    resolved = speedrun_seed_apkg_path()
    assert resolved is not None
    assert os.path.normpath(resolved) == os.path.normpath(str(seed))


def test_speedrun_seed_apkg_path_falls_back_to_dev_repo(tmp_path, monkeypatch) -> None:
    # Packaged file absent -> fall back to the in-repo dev path
    # (speedrun/out/gre_math_seed.apkg). Simulate both dirs; only the dev one has
    # the file.
    import aqt.speedrun_logic as sl

    packaged = tmp_path / "pkgdata"  # exists but has no seed apkg
    packaged.mkdir()
    dev_out = tmp_path / "speedrun" / "out"
    dev_out.mkdir(parents=True)
    dev_seed = dev_out / SEED_APKG_NAME
    dev_seed.write_bytes(b"x")

    monkeypatch.setattr(sl, "_aqt_data_dir", lambda: packaged)
    monkeypatch.setattr(sl, "_dev_repo_seed_paths", lambda: [dev_seed])

    resolved = speedrun_seed_apkg_path()
    assert resolved is not None
    assert os.path.normpath(resolved) == os.path.normpath(str(dev_seed))


def test_speedrun_seed_apkg_path_none_when_nowhere(tmp_path, monkeypatch) -> None:
    # Neither packaged nor dev path has the file -> None (hook then no-ops).
    import aqt.speedrun_logic as sl

    packaged = tmp_path / "pkgdata"
    packaged.mkdir()
    monkeypatch.setattr(sl, "_aqt_data_dir", lambda: packaged)
    monkeypatch.setattr(sl, "_dev_repo_seed_paths", lambda: [])

    assert speedrun_seed_apkg_path() is None


# ---- Part B: SpeedrunMemory bridge parity with SpeedrunHome ----
#
# The merged sidebar shows Practice actions (Start Run / Mini-mock) on ALL pages
# including Memory, firing (pycmd ?? bridgeCommand)(cmd). On DESKTOP the Memory
# dialog's webview HAS pycmd, so those buttons render enabled but used to NO-OP
# because SpeedrunMemory never wired set_bridge_command / _on_bridge_cmd — only
# SpeedrunHome did. SpeedrunMemory must handle the SAME bridge commands.
#
# These tests dispatch at the _on_bridge_cmd/handler level. We bypass the heavy
# Qt __init__ (which builds an AnkiWebView + calls show(), needing a full
# QApplication) via __new__, attach the tiny bit of state the handlers touch,
# and record which action fires per command. No live reviewer/webview needed.

import aqt.speedrun as speedrun_mod  # noqa: E402

# The commands the sidebar can fire that both dialogs must route identically.
_BRIDGE_COMMANDS = [
    "startrun",
    "startrun:import",
    "startrun:customstudy",
    "minimock",
    "speedrun:ai:probe",
    "speedrun:gen:algebra",
]

# Each command's expected action-method name on the dialog.
_EXPECTED_ACTION = {
    "startrun": "_start_run",
    "startrun:import": "_import_deck",
    "startrun:customstudy": "_custom_study",
    "minimock": "_start_mini_mock",
    "speedrun:ai:probe": "_ai_probe",
    "speedrun:gen:algebra": "_ai_generate",
}


def _dispatch_and_record(cls) -> dict[str, str]:
    """Instantiate ``cls`` WITHOUT its Qt __init__, spy on its action methods,
    and return {command -> action-method-name that fired} for every bridge cmd."""
    inst = cls.__new__(cls)  # bypass QDialog/AnkiWebView construction
    fired: dict[str, str] = {}

    def make_spy(name: str):
        def spy(*_args, **_kwargs):
            fired["last"] = name

        return spy

    for action in set(_EXPECTED_ACTION.values()):
        setattr(inst, action, make_spy(action))

    routed: dict[str, str] = {}
    for cmd in _BRIDGE_COMMANDS:
        fired.pop("last", None)
        inst._on_bridge_cmd(cmd)
        routed[cmd] = fired.get("last", "")
    return routed


def test_speedrun_window_routes_all_bridge_commands() -> None:
    # L2 issue #1: the two dialogs (SpeedrunHome/SpeedrunMemory) were collapsed
    # into ONE SpeedrunWindow. The single window must still route every sidebar
    # command to its action (parity is now intrinsic — one class, one dispatch).
    routed = _dispatch_and_record(speedrun_mod.SpeedrunWindow)
    assert routed == _EXPECTED_ACTION


def test_speedrun_window_has_bridge_handler() -> None:
    # The one window must expose the bridge handler + the practice actions (not
    # just be a bare QDialog with no dispatch).
    for attr in ("_on_bridge_cmd", "_start_run", "_start_mini_mock", "_ai_probe"):
        assert hasattr(speedrun_mod.SpeedrunWindow, attr), (
            f"SpeedrunWindow missing {attr}"
        )


def test_no_double_dispatch_alias_reintroduced() -> None:
    # Desktop makes pycmd === bridgeCommand; the sidebar already fires via
    # (pycmd ?? bridgeCommand), i.e. ONE channel. Guard that the Qt side wires the
    # bridge command exactly once, so a refactor can't silently double-register it.
    import inspect

    src = inspect.getsource(speedrun_mod)
    assert src.count("set_bridge_command(") == 1, (
        "expected a single set_bridge_command wiring, "
        f"found {src.count('set_bridge_command(')}"
    )


# ---- L1: Problem-card flow (issue #6) — confidence gate / lock / restore ----
#
# These pin the CARD-TEMPLATE JS/CSS produced by speedrun/seed/build_seed_deck.py
# (the qfmt/afmt/css strings baked into the Problem note type). The four confirmed
# sub-bugs and their template-only fixes:
#   (a) Sure/Think/Guess had no selected state — now classed .speedrun-conf-btn
#       with a .speedrun-conf-selected CSS state applied on click/restore.
#   (b) The bet was never locked in the UI — first click locks the sibling buttons.
#   (c) No confidence-before-answer gate — choices are inert until a bet is placed.
#   (d) The MCQ pick was lost on Show Answer — the afmt {{FrontSide}} re-renders the
#       qfmt, so state must be persisted (sessionStorage, keyed by a stem
#       FINGERPRINT since no {{cid}} token exists) and re-applied by a restoreState()
#       that runs on EVERY script load WITHOUT re-firing pycmd.
# The logged calibration + MCQ pycmd payloads must stay byte-identical (only added
# guarding/restoring). build_seed_deck imports genanki (absent from the qt pyenv),
# so we import it under a tiny genanki stub that captures the Model kwargs, letting
# us read the exact generated template strings without a rebuild.

import importlib.util as _l1_importlib_util  # noqa: E402
import pathlib as _l1_pathlib  # noqa: E402
import sys as _l1_sys  # noqa: E402
import types as _l1_types  # noqa: E402


def _l1_load_build_seed_deck():
    """Import speedrun/seed/build_seed_deck.py under a genanki stub and return the
    module. The stub's Model records (templates, css) so the tests can read the
    generated qfmt/afmt/css strings verbatim — no genanki install, no apkg rebuild.
    """
    g = _l1_types.ModuleType("genanki")

    class _Model:
        def __init__(self, model_id, name, fields=None, templates=None, css=""):
            self.model_id = model_id
            self.name = name
            self.fields = fields
            self.templates = templates
            self.css = css

    class _Deck:
        def __init__(self, *a, **k):
            pass

        def add_note(self, *a, **k):
            pass

    class _Note:
        def __init__(self, *a, **k):
            pass

    class _Package:
        def __init__(self, *a, **k):
            pass

        def write_to_file(self, *a, **k):
            pass

    g.Model = _Model
    g.Deck = _Deck
    g.Note = _Note
    g.Package = _Package
    g.guid_for = lambda *a, **k: "g"

    saved = _l1_sys.modules.get("genanki")
    _l1_sys.modules["genanki"] = g
    try:
        here = _l1_pathlib.Path(__file__).resolve()
        # repo_root/speedrun/seed/build_seed_deck.py — the qt tests live in
        # repo_root/qt/tests, so go up two to the repo root.
        bsd_path = (
            here.parent.parent.parent / "speedrun" / "seed" / "build_seed_deck.py"
        )
        assert bsd_path.exists(), f"build_seed_deck.py not found at {bsd_path}"
        spec = _l1_importlib_util.spec_from_file_location("_l1_bsd", bsd_path)
        mod = _l1_importlib_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is not None:
            _l1_sys.modules["genanki"] = saved
        else:
            _l1_sys.modules.pop("genanki", None)


def _l1_problem_template():
    mod = _l1_load_build_seed_deck()
    tmpl = mod.PROBLEM_MODEL.templates[0]
    return tmpl["qfmt"], tmpl["afmt"], mod.PROBLEM_MODEL.css


def test_l1_conf_buttons_are_classed_and_have_selected_css() -> None:
    # (a) The confidence buttons must carry the .speedrun-conf-btn class + a
    # data-level, and the CSS must define the .speedrun-conf-selected state so a
    # picked bet visibly highlights. Bare inline-onclick buttons had none of this.
    qfmt, _afmt, css = _l1_problem_template()
    assert "speedrun-conf-btn" in qfmt, "conf buttons must be classed"
    assert 'data-level="sure"' in qfmt
    assert 'data-level="think"' in qfmt
    assert 'data-level="guess"' in qfmt
    assert "speedrun-conf-selected" in css, "selected-state CSS must exist"


def test_l1_conf_block_precedes_choices() -> None:
    # (c) Visual order must match the enforced flow: place the confidence block
    # ABOVE {{Choices}} so the learner bets before the options are shown.
    qfmt, _afmt, _css = _l1_problem_template()
    conf_at = qfmt.find("speedrun-conf-btn")
    choices_at = qfmt.find("{{Choices}}")
    assert conf_at != -1 and choices_at != -1
    assert conf_at < choices_at, "confidence block must render before {{Choices}}"


def test_l1_persists_state_and_restores_without_refiring() -> None:
    # (b)+(d) State must persist to sessionStorage (keyed by a stem fingerprint,
    # since no {{cid}} token exists) and be re-applied by a restoreState() that runs
    # on EVERY load — so Show Answer / {{FrontSide}} re-render keeps the selection
    # and lock without re-firing pycmd.
    qfmt, _afmt, _css = _l1_problem_template()
    assert "sessionStorage" in qfmt, "state must be persisted to sessionStorage"
    assert "restoreState" in qfmt, "a restoreState() must re-apply the UI on load"
    # The old runtime-only data-locked early-return is replaced by a
    # fingerprint/sessionStorage check — no bare `data-locked` gate remains.
    assert "getAttribute('data-locked')" not in qfmt, (
        "the broken data-locked runtime early-return must be gone"
    )


def test_l1_choices_gated_until_bet_placed() -> None:
    # (c) The MCQ pick() must be inert until a confidence bet is placed. Guard that
    # pick() consults the persisted confidence before locking/sending.
    qfmt, _afmt, _css = _l1_problem_template()
    # The gate reads the stored confidence key; if absent, pick() bails.
    assert "speedrun:conf:" in qfmt  # the persisted conf key prefix is referenced
    # An inert visual class for the not-yet-enabled choices.
    assert "speedrun-choice-inert" in qfmt or "speedrun-choice-inert" in _afmt, (
        "choices need an inert-until-bet visual state"
    )


def test_l1_pycmd_payloads_unchanged() -> None:
    # The logged calibration + MCQ payloads must stay byte-identical (we only ADD
    # guarding/restoring; we never change what is sent to the backend).
    qfmt, _afmt, _css = _l1_problem_template()
    # Confidence payloads: exact strings the desktop hook parses.
    assert "pycmd('speedrun:conf:sure')" in qfmt
    assert "pycmd('speedrun:conf:think')" in qfmt
    assert "pycmd('speedrun:conf:guess')" in qfmt
    # MCQ payload: the letter-suffixed command (pycmd + bridgeCommand fallback).
    assert "pycmd('speedrun:mcq:'+letter)" in qfmt
    assert "bridgeCommand('speedrun:mcq:'+letter)" in qfmt
    # And the hidden visual-only key span is preserved.
    assert '<span id="mcq-key"' in qfmt


def test_l1_fingerprint_derived_from_stem_not_leaking_across_cards() -> None:
    # No {{cid}} token exists, so state is keyed by a per-card STEM fingerprint.
    # Guard that the template hashes a stem-derived value into the storage key
    # (so two different cards don't share sessionStorage state).
    qfmt, _afmt, _css = _l1_problem_template()
    # A fingerprint host carrying the raw {{Stem}} for hashing, and a fingerprint
    # function feeding the storage key.
    assert "speedrun-fp" in qfmt, "a stem-fingerprint source must exist in qfmt"
    assert "fingerprint" in qfmt or "fp(" in qfmt, (
        "a fingerprint routine must derive the per-card storage key"
    )


# ---- L2 issue #1: ONE Speedrun window (single registry key + in-webview nav) ----
#
# Speedrun used to be TWO top-level QDialog windows (SpeedrunHome + SpeedrunMemory)
# registered as TWO DialogManager keys, so Home and Memory could BOTH be open at
# once (up to 3 windows). They are collapsed into ONE SpeedrunWindow under a SINGLE
# registry key "Speedrun"; Tools->Memory while Home is open must REUSE that one
# window and navigate its webview, and the legacy open:memory 2nd-window spawn is
# replaced by in-webview navigation. (The live on-screen window count is David's
# manual gate; these tests pin the registry + navigation logic without a
# QApplication.)


def test_l2_single_speedrun_registry_key() -> None:
    # Exactly ONE Speedrun key, "Speedrun", mapped to SpeedrunWindow; the two old
    # keys must be gone so a second window can never be spawned.
    import aqt

    dialogs = aqt.DialogManager._dialogs
    assert "Speedrun" in dialogs, "the single 'Speedrun' registry key must exist"
    assert dialogs["Speedrun"][0] is speedrun_mod.SpeedrunWindow
    assert "SpeedrunHome" not in dialogs, "old SpeedrunHome key must be removed"
    assert "SpeedrunMemory" not in dialogs, "old SpeedrunMemory key must be removed"


def _make_bare_window():
    """A SpeedrunWindow with a recording fake webview, bypassing Qt __init__."""
    win = speedrun_mod.SpeedrunWindow.__new__(speedrun_mod.SpeedrunWindow)

    class _FakeWeb:
        def __init__(self) -> None:
            self.loaded: list[str] = []

        def load_sveltekit_page(self, page: str) -> None:
            self.loaded.append(page)

    win.web = _FakeWeb()
    win._current_page = speedrun_mod.SpeedrunWindow.HOME_PAGE
    return win


def test_l2_reopen_navigates_only_when_route_differs() -> None:
    # reopen(route) must be a NO-OP when the requested route matches the loaded
    # page (Tools->Home while Home is open just raises the existing window), and
    # must navigate IN-WEBVIEW when it differs (Tools->Memory reuses the window).
    win = _make_bare_window()
    assert win._current_page == speedrun_mod.SpeedrunWindow.HOME_PAGE

    # Same route -> no navigation.
    win.reopen(None, route=speedrun_mod.SpeedrunWindow.HOME_PAGE)
    assert win.web.loaded == [], "same-route reopen must not reload the webview"

    # Different route -> navigate once, and remember the new page.
    win.reopen(None, route=speedrun_mod.SpeedrunWindow.MEMORY_PAGE)
    assert win.web.loaded == [speedrun_mod.SpeedrunWindow.MEMORY_PAGE]
    assert win._current_page == speedrun_mod.SpeedrunWindow.MEMORY_PAGE

    # Reopening the now-current route is again a no-op.
    win.reopen(None, route=speedrun_mod.SpeedrunWindow.MEMORY_PAGE)
    assert win.web.loaded == [speedrun_mod.SpeedrunWindow.MEMORY_PAGE]


def test_l2_open_memory_bridge_navigates_in_webview_no_second_window() -> None:
    # The legacy "open:memory" bridge command spawned a 2nd dialog window; it must
    # now navigate the SAME webview to the memory page and NEVER call
    # aqt.dialogs.open (which would create/raise a separate window).
    import aqt

    win = _make_bare_window()

    opened: list = []
    orig_open = aqt.dialogs.open
    aqt.dialogs.open = lambda *a, **k: opened.append((a, k))  # type: ignore
    try:
        win._on_bridge_cmd("open:memory")
    finally:
        aqt.dialogs.open = orig_open  # type: ignore

    assert opened == [], "open:memory must not spawn/raise a second window"
    assert win.web.loaded == [speedrun_mod.SpeedrunWindow.MEMORY_PAGE]
    assert win._current_page == speedrun_mod.SpeedrunWindow.MEMORY_PAGE


# ---- L2 issue #2: mini-mock session timer (Qt-free gate + mm:ss formatting) ----

import aqt.speedrun_timer as speedrun_timer  # noqa: E402


def test_l2_timer_deck_gate_predicate() -> None:
    # Only a "Speedrun Mini-Mock" deck (by prefix, so an auto-suffixed duplicate
    # counts) gets the timer; the exam deck / other decks / no deck do NOT.
    assert speedrun_timer.is_mini_mock_deck_name("Speedrun Mini-Mock") is True
    assert speedrun_timer.is_mini_mock_deck_name("Speedrun Mini-Mock+") is True
    assert speedrun_timer.is_mini_mock_deck_name("Speedrun Mini-Mock++") is True
    assert speedrun_timer.is_mini_mock_deck_name("Speedrun::GRE Math") is False
    assert speedrun_timer.is_mini_mock_deck_name("Default") is False
    assert speedrun_timer.is_mini_mock_deck_name("") is False
    assert speedrun_timer.is_mini_mock_deck_name(None) is False


def test_l2_timer_format_mmss_counts_up_honestly() -> None:
    # Count-UP mm:ss. Minutes are NOT capped at 59 (honest elapsed, not a clock),
    # and a negative (clock skew) clamps to 00:00 — never a fake countdown.
    assert speedrun_timer.format_mmss(0) == "00:00"
    assert speedrun_timer.format_mmss(5) == "00:05"
    assert speedrun_timer.format_mmss(65) == "01:05"
    assert speedrun_timer.format_mmss(599) == "09:59"
    assert speedrun_timer.format_mmss(3599) == "59:59"
    assert speedrun_timer.format_mmss(3600) == "60:00"  # not capped at 59
    assert speedrun_timer.format_mmss(-10) == "00:00"  # clamp, no negative


# ---- L2 phase-2: single-window (minimize the base main window on open;
#      GUARANTEED restore on every exit path) ----
#
# Phase-1 collapsed Speedrun into ONE window. Phase-2 makes it feel like a single
# cohesive app: while the Speedrun window is open the base Anki main window is
# MINIMIZED (never hidden — it always keeps a taskbar entry, so the app can never
# be stranded with no visible/taskbar window) and is RESTORED (showNormal + raise)
# whenever Speedrun closes OR routes into the reviewer (which runs in the base
# window, so it MUST be visible there). Reversible via the ``speedrunSingleWindow``
# profile flag (default ON), mirroring ``speedrunSeedImportEnabled``. All of the
# minimize/restore LOGIC lives in tiny Qt-free helpers so it is unit-tested here
# without a QApplication (via __new__ + a recording fake main window), following
# the existing Part-B test style.

from types import SimpleNamespace as _NS  # noqa: E402

import aqt.speedrun_logic as speedrun_logic  # noqa: E402


class _RecordingMw:
    """Minimal stand-in for AnkiQt that records window-state calls in order.

    ``col.decks.select`` records onto the SAME list so a test can assert the
    relative order of the deck-select, close, restore and moveToState steps.
    """

    def __init__(self) -> None:
        self.calls: list = []
        self.col = _NS(
            decks=_NS(select=lambda did: self.calls.append(("select", did)))
        )

    def showMinimized(self) -> None:
        self.calls.append("showMinimized")

    def showNormal(self) -> None:
        self.calls.append("showNormal")

    def raise_(self) -> None:
        self.calls.append("raise_")

    def activateWindow(self) -> None:
        self.calls.append("activateWindow")

    def moveToState(self, state: str) -> None:
        self.calls.append(("moveToState", state))


def _phase2_window(single_window: bool = True, did_minimize: bool = False):
    """A SpeedrunWindow with the phase-2 state attributes set, bypassing Qt
    __init__ (no QApplication/webview), with a recording fake main window."""
    win = speedrun_mod.SpeedrunWindow.__new__(speedrun_mod.SpeedrunWindow)
    win.mw = _RecordingMw()
    win._single_window = single_window
    win._did_minimize_base = did_minimize
    return win


def test_phase2_single_window_flag_defaults_on_and_is_reversible() -> None:
    # The reversible flag mirrors speedrunSeedImportEnabled: default ON when the
    # key is absent, honoured when present, and any failure to read the profile
    # disables it (safe default = classic phase-1, base window never touched).
    read = speedrun_mod._speedrun_single_window_enabled
    assert read(_NS(pm=_NS(profile={}))) is True  # absent key -> default ON
    assert read(_NS(pm=_NS(profile={"speedrunSingleWindow": True}))) is True
    assert read(_NS(pm=_NS(profile={"speedrunSingleWindow": False}))) is False
    assert read(_NS()) is False  # broken/absent profile -> safe default OFF


def test_phase2_minimize_base_called_once_when_flag_on() -> None:
    # On open (flag ON) the base window is minimized exactly once. showMinimized,
    # never hide(): the base window keeps its taskbar entry.
    win = _phase2_window(single_window=True, did_minimize=False)
    win._minimize_base_window()
    assert win.mw.calls == ["showMinimized"]
    assert win._did_minimize_base is True
    # Idempotent: raising/re-showing the window does not repeatedly yank the base
    # window down.
    win._minimize_base_window()
    assert win.mw.calls == ["showMinimized"]


def test_phase2_minimize_base_noop_when_flag_off() -> None:
    # Flag OFF => classic phase-1: the base window is never touched, so nothing to
    # restore later either.
    win = _phase2_window(single_window=False)
    win._minimize_base_window()
    assert win.mw.calls == []
    assert win._did_minimize_base is False


def test_phase2_uses_showminimized_never_hide() -> None:
    # Anti-stranding invariant: the base window is only ever MINIMIZED, never
    # hidden — a minimized window still owns a taskbar entry the user can click.
    import inspect

    src = inspect.getsource(speedrun_mod.SpeedrunWindow._minimize_base_window)
    assert "showMinimized" in src
    assert ".hide(" not in src, "must NEVER hide() the base window (would strand)"


def test_phase2_restore_base_called_when_minimized() -> None:
    # Guaranteed restore: showNormal + raise + activate so the base window is
    # visible again (e.g. for the reviewer, which runs in it).
    win = _phase2_window(did_minimize=True)
    win._restore_base_window()
    assert win.mw.calls == ["showNormal", "raise_", "activateWindow"]


def test_phase2_restore_base_noop_when_not_minimized() -> None:
    # We only ever un-minimize a window WE minimized (so a user who minimized the
    # base window themselves, or the flag-off case, is left untouched).
    win = _phase2_window(did_minimize=False)
    win._restore_base_window()
    assert win.mw.calls == []


def test_phase2_start_run_restores_base_before_review(monkeypatch) -> None:
    # Start Run "ready" launches the reviewer in the BASE window, so the base
    # window MUST be restored BEFORE moveToState("review") — otherwise the
    # reviewer would be rendered into a still-minimized window.
    win = _phase2_window(did_minimize=True)
    win.close = lambda: win.mw.calls.append("close")
    monkeypatch.setattr(
        speedrun_logic,
        "decide_start_run",
        lambda col, deck: _NS(status="ready", deck_id=DeckId(123)),
    )
    win._start_run()
    calls = win.mw.calls
    assert ("select", DeckId(123)) in calls
    assert "close" in calls
    assert "showNormal" in calls
    assert ("moveToState", "review") in calls
    assert calls.index("showNormal") < calls.index(("moveToState", "review"))


def test_phase2_mini_mock_restores_base_before_review(monkeypatch) -> None:
    # The mini-mock "ready" path likewise enters the reviewer in the base window;
    # restore must precede moveToState there too.
    win = _phase2_window(did_minimize=True)
    win.close = lambda: win.mw.calls.append("close")
    monkeypatch.setattr(speedrun_logic, "resolve_mini_mock_size", lambda col: 5)
    monkeypatch.setattr(
        speedrun_logic,
        "decide_mini_mock",
        lambda col, deck: _NS(status="ready", deck_id=DeckId(7)),
    )
    monkeypatch.setattr(
        speedrun_logic,
        "build_mini_mock_deck",
        lambda col, deck, size: DeckId(999),
    )
    win._start_mini_mock()
    calls = win.mw.calls
    assert ("select", DeckId(999)) in calls
    assert "showNormal" in calls
    assert ("moveToState", "review") in calls
    assert calls.index("showNormal") < calls.index(("moveToState", "review"))


def test_phase2_reject_restores_base_window(monkeypatch) -> None:
    # Closing the Speedrun window (user reject()) restores the base window FIRST,
    # before any teardown, so a failure mid-teardown can never leave the app with
    # the base window minimized and no Speedrun window.
    win = _phase2_window(did_minimize=True)
    win.name = speedrun_mod.SpeedrunWindow.DIALOG_NAME
    win.web = _NS(cleanup=lambda: win.mw.calls.append("cleanup"))
    monkeypatch.setattr(speedrun_mod, "saveGeom", lambda *a, **k: None)
    monkeypatch.setattr(speedrun_mod.aqt.dialogs, "markClosed", lambda *a, **k: None)
    # ``QDialog.reject(self)`` on a bare __new__ instance touches the
    # uninitialised C++ object and raises; restore + cleanup already ran BEFORE
    # it (restore is the FIRST statement), which is exactly the guarantee we want.
    try:
        win.reject()
    except Exception:
        pass
    assert win.mw.calls[:3] == ["showNormal", "raise_", "activateWindow"]
    assert win.mw.calls.index("showNormal") < win.mw.calls.index("cleanup")
