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

# Scored-MCQ note type + subdeck (distinct ids; blessed, permanent — never reuse
# the declarative MODEL_ID/DECK_ID). The Problems subdeck lets mini-mock filtered
# searches target ONLY scorable problems.
PROBLEM_MODEL_ID = 2047815909
PROBLEM_DECK_ID = 2059400111
CHOICE_LETTERS = ("A", "B", "C", "D", "E")

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

PROBLEM_MODEL = genanki.Model(
    PROBLEM_MODEL_ID,
    "Speedrun::Problem",
    fields=[
        {"name": "Stem"},
        {"name": "Choices"},
        {"name": "NumericAnswer"},
        {"name": "CorrectAnswer"},
        {"name": "WorkedSolution"},
        {"name": "TopicID"},
        {"name": "TechniqueTag"},
        {"name": "Source"},
        {"name": "IRTParams"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Stem}}"
            '<div style="margin-top:8px;white-space:pre-line">{{Choices}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer">'
            '<div style="margin-bottom:8px"><b>Answer: {{CorrectAnswer}}</b></div>'
            "{{WorkedSolution}}"
            '<div style="font-size:12px;color:#888;margin-top:8px">'
            "Topic: {{TopicID}} &middot; Technique: {{TechniqueTag}} "
            "&middot; Source: {{Source}}</div>",
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


def load_problems() -> list[dict]:
    problems: list[dict] = []
    for name in ("problems_calc.yaml", "problems_linear_algebra.yaml"):
        data = yaml.safe_load((SEED_DIR / name).read_text(encoding="utf-8"))
        problems.extend(data)
    return problems


def _format_choices(choices: list[str]) -> str:
    """Join 5 author-supplied option strings into labeled "(A) .." lines."""
    return "\n".join(f"({letter}) {text}" for letter, text in zip(CHOICE_LETTERS, choices))


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

    problem_deck = genanki.Deck(PROBLEM_DECK_ID, "Speedrun::GRE Math::Problems")
    for p in load_problems():
        topic = p["topic"]
        if topic not in valid_topics:
            raise ValueError(
                f"problem topic {topic!r} is not a scored leaf in gre_math.json"
            )
        note = genanki.Note(
            model=PROBLEM_MODEL,
            fields=[
                p["stem"],
                _format_choices(p["choices"]),
                str(p.get("numeric_answer", "")),
                p["correct"],
                p["worked_solution"],
                topic,
                p["technique"],
                p["source"],
                str(p.get("irt_params", "")),
            ],
            # hierarchical topic tag + flat Speedrun::Problem tag (engine scores
            # Performance via tag:Speedrun::Problem).
            tags=[topic, "Speedrun::Problem"],
            guid=genanki.guid_for(p["stem"], topic, "problem"),  # distinct salt
        )
        problem_deck.add_note(note)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package([deck, problem_deck]).write_to_file(str(OUT))
    return OUT


if __name__ == "__main__":
    path = build()
    print(
        f"wrote {path} ({len(load_notes())} declarative notes, "
        f"{len(load_problems())} problems)"
    )
