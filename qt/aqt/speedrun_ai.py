# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Desktop "Generate practice" AI button — HTTP client + verified-problem import.

SAFETY MODEL (read before touching this file):

- The AI service is EXTERNAL. The ONLY contact is an HTTP call FROM this Qt/Python
  layer. Nothing here is imported into rslib/rsdroid; the engine never sees it.
- OFF-by-default. ``ai_available`` gates the button: unless ``SPEEDRUN_AI_ENABLED``
  is truthy AND a ``/health`` probe reports ``ai_enabled``, the button is DISABLED
  and there is ZERO behaviour change to the app.
- Import ONLY VERIFIED problems. The service returns only verified ones, but we
  still trust nothing: ``parse_generate_response`` accepts only a well-formed
  ``status:"ok"`` payload with a ``problems`` list, and ``import_problems`` skips
  any malformed problem and NEVER writes for an empty/abstained result.
- Undo-safe: each problem becomes a ``Speedrun::Problem`` note via the standard
  ``col.add_note`` path (undoable), in ``Speedrun::GRE Math::Problems`` with the
  seed field layout (mirrors ``speedrun/seed/build_seed_deck.py``), tagged
  ``ai-generated`` and deduped by stem.

The logic here is Qt-free and unit-tested with a real ``Collection`` and no
``QApplication`` (see ``qt/tests/test_speedrun_ai.py``). Only ``qt/aqt/speedrun.py``
imports the Qt-touching entry point ``run_generate`` and wires the callback.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from anki.collection import Collection

# The seed's scored-MCQ note type (id 2047815909, UNCHANGED). We resolve it by
# NAME at runtime and never mutate the model, so the frozen id is preserved.
PROBLEM_NOTETYPE = "Speedrun::Problem"

# The Problems subdeck the seed builder writes to and the mini-mock draws from.
# Imported AI problems land here so they feed Performance / mini-mock automatically.
PROBLEM_DECK = "Speedrun::GRE Math::Problems"

# Tag applied to every AI-generated problem so it is discoverable / auditable and
# distinguishable from the hand-authored seed bank.
AI_TAG = "ai-generated"

# Frozen service contract defaults.
DEFAULT_SERVICE_URL = "http://127.0.0.1:8000"
GENERATE_COUNT = 5
# Short timeouts: a slow/absent service must degrade to "not available" fast, not
# freeze the (background) thread. Generation is heavier than a health ping.
HEALTH_TIMEOUT_S = 2.0
GENERATE_TIMEOUT_S = 60.0

CHOICE_LETTERS = ("A", "B", "C", "D", "E")


# ---- Config / environment -------------------------------------------------


def service_url() -> str:
    """Base URL of the external AI service. ``SPEEDRUN_AI_URL`` overrides the
    default; a trailing slash is stripped so path joins are clean."""
    return os.environ.get("SPEEDRUN_AI_URL", DEFAULT_SERVICE_URL).rstrip("/")


def env_enabled() -> bool:
    """True iff ``SPEEDRUN_AI_ENABLED`` is set to a truthy value. This is the
    OFF-by-default master switch: absent/0/false => the feature is off."""
    val = os.environ.get("SPEEDRUN_AI_ENABLED", "").strip().lower()
    return val not in ("", "0", "false", "no", "off")


# ---- Availability ---------------------------------------------------------


def ai_available(
    *,
    env_enabled: bool,
    probe: Callable[[], Optional[dict[str, Any]]],
) -> bool:
    """Whether the "Generate practice" button may be enabled.

    Requires BOTH the env master switch AND a ``/health`` probe that returns
    ``{"ai_enabled": true, ...}``. ``probe`` is injected so this is testable with
    no network; any exception (connection refused / timeout) or a non-enabled /
    malformed response => not available (button disabled, zero behaviour change)."""
    if not env_enabled:
        return False
    try:
        health = probe()
    except Exception:
        return False
    if not isinstance(health, dict):
        return False
    return bool(health.get("ai_enabled"))


def probe_health() -> Optional[dict[str, Any]]:
    """GET ``{SPEEDRUN_AI_URL}/health`` with a short timeout. Returns the parsed
    JSON dict, or None on any error (unreachable/timeout/bad JSON/503). Never
    raises — the caller treats None as "not available"."""
    return _http_get_json(f"{service_url()}/health", HEALTH_TIMEOUT_S)


def is_ai_available() -> bool:
    """Full availability check for the running app: env switch AND live /health."""
    return ai_available(env_enabled=env_enabled(), probe=probe_health)


# ---- HTTP seam (stdlib urllib; no new dependency) -------------------------


def _http_get_json(url: str, timeout: float) -> Optional[dict[str, Any]]:
    """GET a JSON object. Returns None on any network/parse error (no raise).
    A 503 (service disabled) surfaces as an HTTPError -> None -> not available."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _http_post_json(
    url: str, payload: dict[str, Any], timeout: float
) -> Optional[dict[str, Any]]:
    """POST a JSON body and return the parsed JSON object, or None on any
    network/parse error (including a 503 when the service is disabled)."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def fetch_generate_batch(
    topic: str, count: int = GENERATE_COUNT
) -> Optional[dict[str, Any]]:
    """POST ``/generate_batch`` for a topic. Returns the raw parsed response dict
    or None on any failure. This is the injectable network seam: tests pass their
    own ``fetch`` to ``run_generate`` so no socket is opened."""
    return _http_post_json(
        f"{service_url()}/generate_batch",
        {"topic": topic, "count": count},
        GENERATE_TIMEOUT_S,
    )


# ---- Response parsing (frozen contract) -----------------------------------


def parse_generate_response(resp: Any) -> list[dict[str, Any]]:
    """Extract the VERIFIED problems list from a /generate_batch response.

    Trust nothing: only a dict with ``status=="ok"`` and a ``problems`` LIST is
    accepted; anything else (None, error status, missing/!list problems, an
    abstained ``produced:0`` result) yields an empty list so we import nothing."""
    if not isinstance(resp, dict):
        return []
    if resp.get("status") != "ok":
        return []
    problems = resp.get("problems")
    if not isinstance(problems, list):
        return []
    return [p for p in problems if isinstance(p, dict)]


# ---- Choice formatting (mirror the seed builder EXACTLY) -------------------


def _choice_text_html(text: str) -> str:
    """Escape only ``<`` and ``>`` (NOT ``&``) for embedding one option inside a
    choice element. Mirrors ``build_seed_deck._choice_text_html``: ``&`` stays raw
    because matrix options use it as the LaTeX column separator, and escaping the
    angle brackets keeps MathJax ``\\( \\)`` spans intact."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def format_choices(choices: list[str]) -> str:
    """Render option strings as the clickable A-E element block, byte-for-byte
    like ``build_seed_deck._format_choices`` so AI problems render and auto-grade
    exactly like the seed bank (the MCQ qfmt script binds ``#speedrun-choices``)."""
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


# ---- Import (undo-safe) ---------------------------------------------------


def _valid_problem(p: dict[str, Any]) -> bool:
    """A problem is importable only if it carries the fields we need to build a
    scorable note: a non-empty stem, a choices list, and a correct-answer letter
    in A-E that INDEXES AN ACTUALLY RENDERED CHOICE. Trust nothing — a half-formed
    payload is skipped, never half-imported.

    ``format_choices`` renders exactly one button per choice by zipping the choice
    list against ``CHOICE_LETTERS`` (A-E). So a key that is a valid letter but
    indexes no rendered choice (e.g. ``correct_answer="D"`` with only 3 choices,
    or any key when ``len(choices) > len(CHOICE_LETTERS)`` silently drops the
    overflow) would import an entry the learner can NEVER answer correctly:
    ``reconcile_mcq`` grades ``chosen == key`` False on every attempt, polluting
    the OBJECTIVE ``speedrun:mcq_attempts`` Performance signal with an unwinnable
    row. Reject such a problem here (this consistency check is the module's job —
    the contract is "trust nothing" from the external service)."""
    stem = p.get("stem")
    choices = p.get("choices")
    correct = p.get("correct_answer")
    if not isinstance(stem, str) or not stem.strip():
        return False
    if not isinstance(choices, list) or not choices:
        return False
    # More choices than renderable letters => the overflow is silently dropped
    # by format_choices (a misleading MCQ). Only up to len(CHOICE_LETTERS) render.
    if len(choices) > len(CHOICE_LETTERS):
        return False
    if not isinstance(correct, str):
        return False
    letter = correct.strip().upper()
    if letter not in CHOICE_LETTERS:
        return False
    # The key must index an actually rendered choice: 0 <= index < len(choices).
    if CHOICE_LETTERS.index(letter) >= len(choices):
        return False
    return True


def existing_stems(col: Collection) -> set[str]:
    """The set of Stem field values already present among ``Speedrun::Problem``
    notes. Used to dedupe: a problem whose stem already exists is skipped."""
    stems: set[str] = set()
    try:
        nids = col.find_notes(f'note:"{PROBLEM_NOTETYPE}"')
    except Exception:
        return stems
    for nid in nids:
        try:
            note = col.get_note(nid)
        except Exception:
            continue
        try:
            stems.add(note["Stem"])
        except Exception:
            continue
    return stems


def _set_field(note: Any, field: str, value: str) -> None:
    """Set a note field by name if the model has it (defensive: the model is the
    frozen seed model, but a field rename upstream must not crash the import)."""
    try:
        note[field] = value
    except Exception:
        pass


def import_problems(col: Collection, topic: str, problems: list[dict[str, Any]]) -> int:
    """Import VERIFIED problems as ``Speedrun::Problem`` notes; return the count
    ACTUALLY added (never claim more than were written).

    - Resolves the model by NAME (id 2047815909 preserved; never mutated) and the
      Problems subdeck by name (get-or-create). A missing model => 0 added, no crash.
    - Fields set exactly like ``build_seed_deck``: Stem, Choices (same clickable
      A-E HTML), CorrectAnswer (the letter), WorkedSolution, Source (citation),
      TopicID, TechniqueTag (when present).
    - Every note is tagged ``ai-generated`` plus the flat ``Speedrun::Problem`` tag
      and the hierarchical topic tag (matching the seed convention).
    - Deduped by stem: skips a problem whose stem already exists among
      ``Speedrun::Problem`` notes OR appeared earlier in this same batch.
    - Empty/abstained input imports nothing (returns 0).
    - Uses the standard undoable ``col.add_note`` path.
    """
    if not problems:
        return 0
    model = col.models.by_name(PROBLEM_NOTETYPE)
    if model is None:
        # Seed never imported: nothing to attach notes to. Safe no-op.
        return 0
    deck_id = col.decks.id(PROBLEM_DECK)  # get-or-create the Problems subdeck
    if deck_id is None:
        return 0

    seen = existing_stems(col)
    added = 0
    for p in problems:
        if not _valid_problem(p):
            continue
        stem = p["stem"]
        if stem in seen:
            continue  # dedupe (existing bank or earlier in this batch)
        seen.add(stem)

        note = col.new_note(model)
        _set_field(note, "Stem", stem)
        _set_field(note, "Choices", format_choices(list(p.get("choices", []))))
        _set_field(note, "CorrectAnswer", str(p["correct_answer"]).strip().upper())
        _set_field(note, "WorkedSolution", str(p.get("worked_solution", "")))
        _set_field(note, "TopicID", topic)
        _set_field(note, "TechniqueTag", str(p.get("technique_tag", "")))
        _set_field(note, "Source", str(p.get("source_citation", "")))
        # Tags mirror the seed (topic + flat Speedrun::Problem) + the AI marker.
        note.tags = [topic, PROBLEM_NOTETYPE, AI_TAG]
        col.add_note(note, deck_id)
        added += 1
    return added


# ---- Qt entry point (the only Qt-adjacent code) ---------------------------


def run_generate(
    col: Collection,
    topic: str,
    *,
    fetch: Callable[[str, int], Optional[dict[str, Any]]] | None = None,
    count: int = GENERATE_COUNT,
) -> dict[str, Any]:
    """Fetch a verified batch for ``topic`` and import it. Returns a small result
    dict for the JS callback: ``{"topic", "added", "error"}``.

    Runs on a background thread (called via QueryOp in speedrun.py); ``fetch`` is
    injectable for tests. Network/parse failures degrade to ``added:0`` with an
    ``error`` string — never a crash. ``added`` is the count ACTUALLY written, so
    the UI never claims problems were added when none were."""
    do_fetch = fetch or fetch_generate_batch
    try:
        resp = do_fetch(topic, count)
    except Exception as exc:  # defense-in-depth; the seams already swallow errors
        return {"topic": topic, "added": 0, "error": f"request failed: {exc}"}
    if resp is None:
        return {"topic": topic, "added": 0, "error": "service unreachable"}
    problems = parse_generate_response(resp)
    if not problems:
        # Covered-but-abstained or an error payload: import nothing, honestly.
        return {"topic": topic, "added": 0, "error": ""}
    added = import_problems(col, topic, problems)
    return {"topic": topic, "added": added, "error": ""}
