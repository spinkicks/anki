# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "seed"))

import build_seed_deck as bsd  # noqa: E402


def test_min_note_count():
    notes = bsd.load_notes()
    assert len(notes) >= 30, "Wednesday floor is >=30 declarative notes"


def test_every_note_has_source_and_valid_topic():
    valid = {t["id"] for t in json.loads(bsd.PROFILE.read_text("utf-8"))["topics"]}
    for n in bsd.load_notes():
        assert n["front"].strip()
        assert n["back"].strip()
        assert n["source"].strip(), f"missing Source on {n['front']!r}"
        assert n["topic"] in valid, f"unknown topic {n['topic']!r}"


def test_build_produces_apkg():
    path = bsd.build()
    assert path.exists()
    assert path.stat().st_size > 0


# --- Problem bank (Speedrun::Problem MCQ note type) ---

VALID_LETTERS = {"A", "B", "C", "D", "E"}


def _scored_leaves():
    return bsd._leaf_topic_ids()


def test_problem_min_count():
    problems = bsd.load_problems()
    assert len(problems) >= 40, "Friday floor is >=40 scorable MCQ problems"


def test_every_problem_valid():
    scored = _scored_leaves()
    for p in bsd.load_problems():
        label = p.get("stem", "<no stem>")
        assert p["stem"].strip(), f"empty stem: {label!r}"
        choices = p["choices"]
        assert isinstance(choices, list) and len(choices) == 5, (
            f"need exactly 5 choices: {label!r}"
        )
        for c in choices:
            assert str(c).strip(), f"empty choice in {label!r}"
        assert p["correct"] in VALID_LETTERS, f"bad correct letter in {label!r}"
        assert p["worked_solution"].strip(), f"empty worked_solution: {label!r}"
        assert p["technique"].strip(), f"empty technique: {label!r}"
        assert p["source"].strip(), f"empty source: {label!r}"
        assert p["topic"] in scored, f"unknown/non-scored topic {p['topic']!r} in {label!r}"


def test_problem_correct_letter_in_range():
    for p in bsd.load_problems():
        idx = ord(p["correct"]) - ord("A")
        assert 0 <= idx <= 4, f"correct index out of range in {p['stem']!r}"
        assert idx < len(p["choices"]), (
            f"correct letter maps past choices in {p['stem']!r}"
        )


def test_build_produces_apkg_with_problems():
    path = bsd.build()
    assert path.exists()
    assert path.stat().st_size > 0
