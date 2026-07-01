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
