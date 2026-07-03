# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Tests for the desktop "Generate practice" AI button plumbing.

Two Qt-free concerns are covered:

1. IMPORT — given the frozen /generate_batch contract shape (a list of VERIFIED
   problem dicts), ``import_problems`` creates ``Speedrun::Problem`` notes in the
   Problems subdeck with the seed field layout, tags each ``ai-generated``,
   dedupes by stem, and imports NOTHING for an empty/abstained result. The
   PROBLEM_MODEL_ID (2047815909) is never mutated.

2. AVAILABILITY — ``ai_available`` is True only when AI is enabled AND a /health
   probe reports ``ai_enabled``. The probe is injected so no test hits the
   network; a disabled env or an unreachable/timeout probe => not available.

The HTTP call itself lives behind an injectable ``fetch`` seam so these tests
never open a socket.
"""

from __future__ import annotations

import os
import tempfile

from anki.collection import Collection
from aqt import speedrun_ai

PROBLEM_DECK = "Speedrun::GRE Math::Problems"


def _empty_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def _make_problem_model(col: Collection):
    """Create a note type literally named ``Speedrun::Problem`` with the seed
    field set. Mirrors build_seed_deck.PROBLEM_MODEL's fields so import can set
    them by name. (The real model id is 2047815909; a fresh test model gets an
    auto id, and import must NOT depend on/overwrite that id — it resolves the
    model by NAME.)"""
    mm = col.models
    mm.current()  # materialise stock notetypes on a fresh collection
    nt = mm.new(speedrun_ai.PROBLEM_NOTETYPE)
    for field in (
        "Stem",
        "Choices",
        "NumericAnswer",
        "CorrectAnswer",
        "WorkedSolution",
        "TopicID",
        "TechniqueTag",
        "Source",
        "IRTParams",
        "ExampleFirst",
    ):
        mm.add_field(nt, mm.new_field(field))
    tmpl = mm.new_template("Card 1")
    tmpl["qfmt"] = "{{Stem}}"
    tmpl["afmt"] = "{{FrontSide}}<hr>{{CorrectAnswer}}"
    mm.add_template(nt, tmpl)
    mm.add(nt)
    return nt


def _verified_problem(stem: str = "What is 2+2?", correct: str = "C") -> dict:
    """One problem in the frozen /generate_batch contract shape."""
    return {
        "stem": stem,
        "choices": ["1", "2", "4", "5", "6"],
        "correct_answer": correct,
        "worked_solution": "2+2=4, so the answer is C.",
        "source_citation": "Seed corpus §1",
    }


# ---- IMPORT ---------------------------------------------------------------


def test_import_creates_problem_notes_with_seed_fields() -> None:
    col = _empty_col()
    try:
        _make_problem_model(col)
        problems = [
            _verified_problem("Q one", "A"),
            _verified_problem("Q two", "B"),
        ]
        added = speedrun_ai.import_problems(col, "calc::limits", problems)
        assert added == 2

        nids = col.find_notes('note:"Speedrun::Problem"')
        assert len(nids) == 2
        note = col.get_note(nids[0])
        # Fields set exactly like the seed builder.
        assert note["Stem"] in ("Q one", "Q two")
        assert note["CorrectAnswer"] in ("A", "B")
        assert note["WorkedSolution"]
        assert note["Source"] == "Seed corpus §1"
        assert note["TopicID"] == "calc::limits"
        # Choices rendered as the clickable A-E element block (seed layout).
        assert 'id="speedrun-choices"' in note["Choices"]
        assert 'data-letter="A"' in note["Choices"]
        assert 'data-letter="E"' in note["Choices"]
        # Tagged ai-generated (and carries the flat Speedrun::Problem tag + topic).
        assert speedrun_ai.AI_TAG in note.tags
        # Landed in the Problems subdeck.
        cards = note.cards()
        assert cards
        assert col.decks.name(cards[0].did) == PROBLEM_DECK
    finally:
        col.close()


def test_import_model_id_unchanged() -> None:
    # The Speedrun::Problem model id must never be mutated by an import.
    col = _empty_col()
    try:
        nt = _make_problem_model(col)
        model_id_before = nt["id"]
        speedrun_ai.import_problems(col, "calc::limits", [_verified_problem()])
        after = col.models.by_name(speedrun_ai.PROBLEM_NOTETYPE)
        assert after is not None
        assert after["id"] == model_id_before
    finally:
        col.close()


def test_import_dedupes_identical_stem() -> None:
    col = _empty_col()
    try:
        _make_problem_model(col)
        p = _verified_problem("Same stem?", "D")
        first = speedrun_ai.import_problems(col, "calc::limits", [p])
        assert first == 1
        # Re-importing the identical stem must add nothing (deduped).
        second = speedrun_ai.import_problems(col, "calc::limits", [p])
        assert second == 0
        assert len(col.find_notes('note:"Speedrun::Problem"')) == 1
    finally:
        col.close()


def test_import_dedupes_within_one_batch() -> None:
    # Two problems with the same stem in ONE batch => only the first is added.
    col = _empty_col()
    try:
        _make_problem_model(col)
        dupe = _verified_problem("Twin", "A")
        added = speedrun_ai.import_problems(
            col, "calc::limits", [dupe, _verified_problem("Twin", "B")]
        )
        assert added == 1
        assert len(col.find_notes('note:"Speedrun::Problem"')) == 1
    finally:
        col.close()


def test_import_empty_result_imports_nothing() -> None:
    # An abstained/uncovered result (produced:0, problems:[]) writes no notes.
    col = _empty_col()
    try:
        _make_problem_model(col)
        added = speedrun_ai.import_problems(col, "calc::limits", [])
        assert added == 0
        assert col.find_notes('note:"Speedrun::Problem"') == []
    finally:
        col.close()


def test_import_skips_malformed_problem() -> None:
    # Defensive: a problem missing a required field (trust nothing) is skipped,
    # never imported as a half-note. Valid siblings still import.
    col = _empty_col()
    try:
        _make_problem_model(col)
        good = _verified_problem("Good one", "A")
        bad = {"stem": "", "choices": [], "correct_answer": "Z"}
        added = speedrun_ai.import_problems(col, "calc::limits", [bad, good])
        assert added == 1
        nids = col.find_notes('note:"Speedrun::Problem"')
        assert len(nids) == 1
        assert col.get_note(nids[0])["Stem"] == "Good one"
    finally:
        col.close()


def test_import_missing_model_returns_zero_no_crash() -> None:
    # If the Speedrun::Problem model isn't present (seed never imported), import
    # must be a safe no-op (0 added), never a crash.
    col = _empty_col()
    try:
        added = speedrun_ai.import_problems(col, "calc::limits", [_verified_problem()])
        assert added == 0
    finally:
        col.close()


# ---- CHOICE FORMATTING (mirror seed exactly) ------------------------------


def test_format_choices_matches_seed_shape() -> None:
    html = speedrun_ai.format_choices(["a", "b", "c", "d", "e"])
    assert html.startswith('<div id="speedrun-choices"')
    for letter in ("A", "B", "C", "D", "E"):
        assert f'data-letter="{letter}"' in html
    # <>/& handling mirrors the seed: < and > escaped, & left raw.
    esc = speedrun_ai.format_choices(["\\(|x|<e\\)"])
    assert "&lt;e" in esc


# ---- AVAILABILITY ---------------------------------------------------------


def test_ai_available_true_when_enabled_and_healthy() -> None:
    # Env enabled + a /health probe that reports ai_enabled => available.
    assert speedrun_ai.ai_available(
        env_enabled=True, probe=lambda: {"status": "ok", "ai_enabled": True}
    )


def test_ai_available_false_when_env_disabled() -> None:
    # Even a healthy probe can't override a disabled env (OFF-by-default).
    assert not speedrun_ai.ai_available(
        env_enabled=False, probe=lambda: {"status": "ok", "ai_enabled": True}
    )


def test_ai_available_false_when_probe_reports_disabled() -> None:
    assert not speedrun_ai.ai_available(
        env_enabled=True, probe=lambda: {"status": "ok", "ai_enabled": False}
    )


def test_ai_available_false_when_probe_unreachable() -> None:
    # A probe that raises (connection refused / timeout) => not available; the
    # button stays disabled and there is zero behaviour change.
    def boom():
        raise ConnectionError("refused")

    assert not speedrun_ai.ai_available(env_enabled=True, probe=boom)


def test_ai_available_false_when_probe_returns_none() -> None:
    assert not speedrun_ai.ai_available(env_enabled=True, probe=lambda: None)


def test_env_enabled_reads_truthy_flag(monkeypatch) -> None:
    monkeypatch.setenv("SPEEDRUN_AI_ENABLED", "1")
    assert speedrun_ai.env_enabled()
    monkeypatch.setenv("SPEEDRUN_AI_ENABLED", "true")
    assert speedrun_ai.env_enabled()
    monkeypatch.setenv("SPEEDRUN_AI_ENABLED", "0")
    assert not speedrun_ai.env_enabled()
    monkeypatch.delenv("SPEEDRUN_AI_ENABLED", raising=False)
    assert not speedrun_ai.env_enabled()


def test_service_url_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("SPEEDRUN_AI_URL", raising=False)
    assert speedrun_ai.service_url() == "http://127.0.0.1:8000"
    monkeypatch.setenv("SPEEDRUN_AI_URL", "http://example.test:9001/")
    # Trailing slash normalised so path joins are clean.
    assert speedrun_ai.service_url() == "http://example.test:9001"


# ---- RESPONSE PARSING (frozen contract) -----------------------------------


def test_parse_generate_response_returns_only_problems_list() -> None:
    resp = {
        "status": "ok",
        "topic": "calc::limits",
        "requested": 5,
        "produced": 2,
        "problems": [_verified_problem("A"), _verified_problem("B")],
    }
    problems = speedrun_ai.parse_generate_response(resp)
    assert len(problems) == 2


def test_parse_generate_response_abstained_is_empty() -> None:
    # Uncovered topic: produced:0, problems:[] => never fabricate a problem.
    resp = {"status": "ok", "topic": "x", "requested": 5, "produced": 0, "problems": []}
    assert speedrun_ai.parse_generate_response(resp) == []


def test_parse_generate_response_bad_payload_is_empty() -> None:
    # Non-dict / missing problems / non-ok status => trust nothing, import nothing.
    assert speedrun_ai.parse_generate_response(None) == []
    assert speedrun_ai.parse_generate_response({"status": "error"}) == []
    assert speedrun_ai.parse_generate_response({"status": "ok"}) == []
    assert speedrun_ai.parse_generate_response({"problems": "nope"}) == []
