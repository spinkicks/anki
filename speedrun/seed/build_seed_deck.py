# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Deterministic YAML -> .apkg builder for the Speedrun GRE-Math seed deck.

No AI: cards are hand-authored in seed/*.yaml. Fixed IDs make output stable and
importable identically on desktop and AnkiDroid.
"""
from __future__ import annotations

import json
from pathlib import Path

import genanki
import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "seed"
OUT = ROOT / "out" / "gre_math_seed.apkg"
PROFILE = ROOT / "exam_profiles" / "gre_math.json"

# Fixed IDs (chosen once; do not change or existing imports will duplicate).
MODEL_ID = 1607392319
DECK_ID = 2059400110

MODEL = genanki.Model(
    MODEL_ID,
    "Speedrun::Declarative",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
        {"name": "TopicID"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Back}}'
            '<div style="font-size:12px;color:#888;margin-top:8px">'
            "Topic: {{TopicID}} &middot; Source: {{Source}}</div>",
        }
    ],
    # Bundled MathJax rendering is handled by Anki's built-in MathJax on \\( \\).
)


def _leaf_topic_ids() -> set[str]:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    return {t["id"] for t in profile["topics"] if t["ets_weight"] > 0.0}


def load_notes() -> list[dict]:
    notes: list[dict] = []
    for name in ("cards_calc.yaml", "cards_linear_algebra.yaml"):
        data = yaml.safe_load((SEED_DIR / name).read_text(encoding="utf-8"))
        notes.extend(data)
    return notes


def build() -> Path:
    valid_topics = _leaf_topic_ids()
    deck = genanki.Deck(DECK_ID, "Speedrun::GRE Math")
    for n in load_notes():
        topic = n["topic"]
        if topic not in valid_topics:
            raise ValueError(f"note topic {topic!r} is not a scored leaf in gre_math.json")
        note = genanki.Note(
            model=MODEL,
            fields=[n["front"], n["back"], topic, n["source"]],
            tags=[topic],  # hierarchical tag == topic id; :: preserved
            guid=genanki.guid_for(n["front"], topic),  # stable across runs
        )
        deck.add_note(note)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(deck).write_to_file(str(OUT))
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({len(load_notes())} notes)")
