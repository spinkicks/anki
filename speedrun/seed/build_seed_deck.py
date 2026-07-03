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

# LS2 faded worked-example reveal (Huang 2023: lead with worked steps, then FADE
# support). Pure client JS, no bridge/persistence/scheduling — the answer side
# renders the WorkedSolution as steps hidden behind "Reveal next step", so the
# learner attempts each step before seeing it. Steps split on sentence/step
# boundaries: a period or colon followed by whitespace. This delimiter was
# ground-truthed against every seed WorkedSolution — 0 of 134 split points fall
# inside a MathJax \\( \\) span (no in-span period is ever followed by space), so
# LaTeX is never severed. Graceful degradation: the raw solution is emitted in a
# <div id="ws-raw"> that the JS reads then replaces; if JS is off, that div (and
# a <noscript>) show the full solution. WITHIN-card only — cross-rep fading needs
# schedule state the template cannot read (future upgrade).
FADED_REVEAL_JS = (
    "<div id=\"ws-steps\"></div>"
    "<noscript>{{WorkedSolution}}</noscript>"
    "<div id=\"ws-raw\" style=\"display:none\">{{WorkedSolution}}</div>"
    "<script>(function(){"
    "var raw=document.getElementById('ws-raw');"
    "var host=document.getElementById('ws-steps');"
    "if(!raw||!host){return;}"
    # Split the rendered solution HTML on sentence/step boundaries (period or
    # colon + whitespace). Lookbehind keeps the terminator on the step. Verified
    # never to cut a \\( \\) span for the seed content.
    "var html=raw.innerHTML;"
    "var parts=html.split(/(?<=[.:])\\s+/).map(function(s){return s.trim();})"
    ".filter(function(s){return s.length;});"
    # 0 or 1 step: nothing to fade — just show the whole solution.
    "if(parts.length<2){host.innerHTML=raw.innerHTML;return;}"
    "var shown=0;"
    "var btn=document.createElement('button');"
    "btn.type='button';"
    "btn.textContent='Reveal next step';"
    "btn.style.marginTop='8px';"
    "function typeset(){"
    # Re-run MathJax on newly revealed steps (desktop + AnkiDroid both bundle it).
    "if(window.MathJax&&window.MathJax.typesetPromise){"
    "window.MathJax.typesetPromise([host]);}}"
    "function revealNext(){"
    "if(shown>=parts.length){return;}"
    "var d=document.createElement('div');"
    "d.style.marginTop='6px';"
    "d.innerHTML=parts[shown];"
    "host.appendChild(d);"
    "shown++;"
    "if(shown>=parts.length){"
    "btn.textContent='All steps revealed';btn.disabled=true;}"
    "else{btn.textContent='Reveal next step ('+shown+'/'+parts.length+')';}"
    "typeset();}"
    "host.appendChild(btn);"
    "btn.addEventListener('click',revealNext);"
    "revealNext();"  # reveal the first step immediately (a genuine worked start)
    "})();</script>"
)

# Interactive MCQ auto-grade (thesis-critical: Performance is OBJECTIVELY
# key-checked, not self-rated). The Choices field renders 5 CLICKABLE options
# (see _format_choices). This qfmt script wires them: on the first click it locks
# the selection, fires pycmd("speedrun:mcq:<LETTER>") so the desktop reviewer
# hook (aqt/speedrun_capture.py) can key-check the pick backend-side, and marks
# the correct option green (and, if wrong, the chosen one red). The correct
# letter used for VISUAL marking only comes from a hidden {{CorrectAnswer}} span
# in the field HTML (id="mcq-key") — the AUTHORITATIVE grade is computed backend
# side against the note field, never trusted from this client display value.
# Graceful degradation: if pycmd/bridgeCommand is absent (e.g. a plain preview),
# the click still marks visually and never throws; if JS is off entirely, the
# choices still render (they are plain elements in the field) as a static list.
MCQ_CHOICES_JS = (
    '<span id="mcq-key" style="display:none">{{CorrectAnswer}}</span>'
    "<script>(function(){"
    "var host=document.getElementById('speedrun-choices');"
    "if(!host){return;}"
    # Idempotent: {{FrontSide}} re-runs this on the answer side, but the pick is
    # already locked there (data-locked set), so bail without rebinding.
    "if(host.getAttribute('data-locked')){return;}"
    "var keyEl=document.getElementById('mcq-key');"
    "var key=keyEl?(keyEl.textContent||'').trim().toUpperCase():'';"
    "var choices=host.querySelectorAll('.speedrun-choice');"
    "function send(letter){"
    # Prefer pycmd (desktop); fall back to bridgeCommand; no-op if neither exists
    # (plain preview / Android MVP) so a click never throws.
    "try{"
    "if(typeof pycmd==='function'){pycmd('speedrun:mcq:'+letter);}"
    "else if(typeof bridgeCommand==='function'){"
    "bridgeCommand('speedrun:mcq:'+letter);}"
    "}catch(e){}}"
    "function pick(ev){"
    "if(host.getAttribute('data-locked')){return;}"
    "var btn=ev.currentTarget;"
    "var letter=(btn.getAttribute('data-letter')||'').toUpperCase();"
    "host.setAttribute('data-locked','1');"
    # Send the chosen letter FIRST (grade is backend-side); then mark visually.
    "send(letter);"
    "for(var i=0;i<choices.length;i++){"
    "var c=choices[i];"
    "c.setAttribute('aria-disabled','true');"
    "var l=(c.getAttribute('data-letter')||'').toUpperCase();"
    "if(key&&l===key){c.classList.add('speedrun-correct');}"
    "else if(l===letter){c.classList.add('speedrun-wrong');}"
    "}}"
    "for(var i=0;i<choices.length;i++){"
    "choices[i].addEventListener('click',pick);}"
    "})();</script>"
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
        # LS2 example-first flag (additive; PROBLEM_MODEL_ID unchanged). A content
        # flag: when non-empty, the qfmt shows the fully worked solution UP FRONT
        # as a study example (worked-examples-first for weak/novice topics) before
        # the learner attempts it. Anki conditionals key on non-empty FIELDS (not
        # tags), so this must be a field for {{#ExampleFirst}} to branch. Populated
        # per-problem from the YAML `example_first` key (default empty = off).
        {"name": "ExampleFirst"},
    ],
    templates=[
        {
            "name": "Card 1",
            # Pre-answer confidence buttons (desktop calibration self-bet). Each
            # fires pycmd("speedrun:conf:<level>"); the desktop reviewer hook
            # (aqt/speedrun_capture.py) reads the card id from context and logs
            # the attempt on answer. Anki templates expose NO card-id token, so
            # the level is the only payload. Inert/harmless on Android (no handler
            # registered there in the MVP — no persistence, no error).
            "qfmt": "{{Stem}}"
            '<div style="margin-top:8px">{{Choices}}</div>'
            # Interactive MCQ: wire the clickable choices (lock + pycmd + visual
            # mark). Placed after the Choices field so the elements exist. The
            # backend key-checks the pick; this only marks + reports the letter.
            + MCQ_CHOICES_JS
            # LS2 example-first: for flagged (weak/novice) items show the fully
            # worked solution as a study EXAMPLE before the learner attempts it.
            # Content flag only (non-empty ExampleFirst field) — no scheduling.
            + "{{#ExampleFirst}}"
            '<div style="margin-top:12px;padding:8px;border-left:3px solid #7aa;'
            'background:rgba(120,170,170,0.08)">'
            '<div style="font-size:11px;color:#888;margin-bottom:4px">'
            "Worked example (study this first, then solve above):</div>"
            "{{WorkedSolution}}</div>"
            "{{/ExampleFirst}}"
            '<div style="margin-top:12px;font-size:11px;color:#888">'
            "How sure are you, before you check?</div>"
            '<div style="margin-top:4px">'
            "<button type=\"button\" onclick=\"pycmd('speedrun:conf:sure')\">"
            "Sure</button> "
            "<button type=\"button\" onclick=\"pycmd('speedrun:conf:think')\">"
            "Think</button> "
            "<button type=\"button\" onclick=\"pycmd('speedrun:conf:guess')\">"
            "Guess</button></div>",
            "afmt": '{{FrontSide}}<hr id="answer">'
            '<div style="margin-bottom:8px"><b>Answer: {{CorrectAnswer}}</b></div>'
            # LS2 faded worked-example: reveal the WorkedSolution one step at a
            # time (attempt each step before seeing it). Degrades to full solution
            # when JS is off. See FADED_REVEAL_JS.
            + FADED_REVEAL_JS
            + '<div style="font-size:12px;color:#888;margin-top:8px">'
            "Self-grade: rate Good/Easy only if your answer matched the "
            "correct answer above &mdash; Again/Hard if it didn&rsquo;t.</div>"
            '<div style="font-size:12px;color:#888;margin-top:8px">'
            "Topic: {{TopicID}} &middot; Technique: {{TechniqueTag}} "
            "&middot; Source: {{Source}}</div>",
        }
    ],
    # Clickable-choice styling. Large tap targets (min-height 44px, full-width,
    # block layout) render cleanly at 360px on phones. .speedrun-correct /
    # .speedrun-wrong are applied by MCQ_CHOICES_JS after a pick (green key, red
    # wrong pick). Colours chosen to read on both light and dark Anki themes.
    css=(
        ".speedrun-choices{margin:0}"
        ".speedrun-choice{display:block;width:100%;box-sizing:border-box;"
        "text-align:left;margin:6px 0;padding:10px 12px;min-height:44px;"
        "border:1px solid #b8b8b8;border-radius:8px;background:transparent;"
        "color:inherit;font-size:inherit;line-height:1.4;cursor:pointer;"
        "-webkit-tap-highlight-color:transparent}"
        ".speedrun-choice[aria-disabled='true']{cursor:default}"
        ".speedrun-choice-letter{display:inline-block;min-width:1.6em;"
        "font-weight:bold}"
        ".speedrun-choice.speedrun-correct{border-color:#2e7d32;"
        "background:rgba(46,125,50,0.16)}"
        ".speedrun-choice.speedrun-wrong{border-color:#c62828;"
        "background:rgba(198,40,40,0.16)}"
    ),
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


def _choice_text_html(text: str) -> str:
    """Prepare one option string for embedding inside a choice <span>.

    Escapes only ``<`` and ``>`` — NOT ``&``. Grounded against the seed content:
    a choice like ``\\(|x|<e\\)`` embedded raw makes the HTML tokenizer read
    ``<e\\)</span>`` as a bogus <e...> start tag, swallowing the MathJax ``\\)``
    closer and the </span> (broken render). Escaping ``<``/``>`` to entities lets
    MathJax see the correct textContent (``|x|<e``). ``&`` is left raw on purpose:
    matrix options use ``&`` as the LaTeX column separator (``\\begin{pmatrix}1&4
    …``); ``&amp;`` would break the matrix, and ``&4`` is an invalid HTML entity
    so browsers keep it literal — exactly what MathJax needs."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _format_choices(choices: list[str]) -> str:
    """Render the author-supplied option strings as CLICKABLE elements, one per
    letter A-E, wrapped in a #speedrun-choices host that MCQ_CHOICES_JS binds.

    Each choice is a <button data-letter="X"> carrying its letter badge + the
    option text (LaTeX \\( \\) preserved for Anki's MathJax; see
    _choice_text_html for the <>/& handling). The elements are plain HTML, so if
    JS is off they still render as a readable list; the click behaviour (lock +
    pycmd + green/red marking) is attached by the qfmt script. No new field is
    introduced — this only changes how Choices renders."""
    items = []
    for letter, text in zip(CHOICE_LETTERS, choices):
        items.append(
            f'<button type="button" class="speedrun-choice" data-letter="{letter}">'
            f'<span class="speedrun-choice-letter">{letter}</span> '
            f'<span class="speedrun-choice-text">{_choice_text_html(text)}</span>'
            "</button>"
        )
    return (
        '<div id="speedrun-choices" class="speedrun-choices">'
        + "".join(items)
        + "</div>"
    )


def _truthy(value: object) -> bool:
    """Interpret a YAML example_first flag (bool, int, or string) as on/off."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no")
    return bool(value)


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
        # LS2 example-first flag: truthy YAML `example_first` -> non-empty field
        # (so the qfmt {{#ExampleFirst}} conditional fires) plus a discoverable
        # tag (for filtered-deck searches). Default off = empty field, no tag.
        example_first = "1" if _truthy(p.get("example_first")) else ""
        tags = [topic, "Speedrun::Problem"]
        if example_first:
            tags.append("Speedrun::ExampleFirst")
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
                example_first,
            ],
            # hierarchical topic tag + flat Speedrun::Problem tag (engine scores
            # Performance via tag:Speedrun::Problem) + optional ExampleFirst tag.
            tags=tags,
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
