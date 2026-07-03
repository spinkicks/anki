# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Desktop capture of a pre-answer confidence on Speedrun::Problem attempts.

Zero edits to ``reviewer.py``: two ``gui_hooks`` do the work. A confidence
button in the Problem card's question template fires ``pycmd("speedrun:conf:
<level>")``; the ``webview_did_receive_js_message`` filter catches it (guarding
that we are in the Reviewer on a Speedrun::Problem card) and STASHES the pending
confidence keyed by card id. When the card is answered,
``reviewer_did_answer_card`` reconciles the stash with the answer's ease and the
just-written revlog id, appending a calibration attempt to the config-blob log
(``speedrun:calibration_log``) via the collection config API.

``correct`` is the SELF-RATED outcome (ease >= 3, i.e. Good/Easy — the same
honesty rule as the engine's ``topic_problem_stats``), NOT key-checked accuracy.

The parse / guard / reconcile logic is factored into pure, Qt-free functions so
it can be unit-tested with a real ``Collection`` and no ``QApplication`` (see
``qt/tests/test_speedrun.py``). Only ``register()`` and the two thin hook
callbacks touch Qt.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import aqt.reviewer
    from anki.cards import Card
    from anki.collection import Collection

# The confidence levels a Problem card may report. Kept in sync with the engine's
# confidence_to_prob (Sure=0.9, Think=0.65, Guess=0.4); the engine is the single
# source of the probabilities, so we only validate the label here.
CONF_LEVELS = ("sure", "think", "guess")

# The note type whose attempts we capture. Matches the seed deck's Problem model
# and the engine's Speedrun::Problem tag/notetype convention.
PROBLEM_NOTETYPE = "Speedrun::Problem"

# Config key holding the JSON attempt log (mirrors the engine's
# CALIBRATION_LOG_CONFIG_KEY; a plain speedrun:* config blob, no schema change).
CALIBRATION_LOG_KEY = "speedrun:calibration_log"

# Pending confidence per card id, set when a confidence button is pressed and
# consumed when that card is answered. Module-level (the reviewer is a singleton).
_pending: dict[int, str] = {}


def parse_conf_message(message: str) -> Optional[str]:
    """Return the confidence level from a ``speedrun:conf:<level>`` message, or
    None if the message isn't a (valid) confidence command. Case-insensitive;
    an unknown level is rejected (None) rather than silently mis-graded."""
    prefix = "speedrun:conf:"
    if not message.startswith(prefix):
        return None
    level = message[len(prefix) :].strip().lower()
    return level if level in CONF_LEVELS else None


def is_problem_card(card: Card | None) -> bool:
    """True iff ``card`` is a Speedrun::Problem card (the only cards we capture)."""
    if card is None:
        return False
    try:
        return card.note_type()["name"] == PROBLEM_NOTETYPE
    except Exception:
        # A missing/deleted note type must never crash the reviewer.
        return False


def stash_pending(cid: int, level: str) -> None:
    """Record the pending confidence for a card id (last press wins)."""
    _pending[cid] = level


def take_pending(cid: int) -> Optional[str]:
    """Pop and return the pending confidence for a card id, or None."""
    return _pending.pop(cid, None)


def clear_pending(cid: int) -> None:
    """Drop any pending confidence for a card id without writing an attempt.
    Used when a card is buried/suspended before it is answered, so a later
    answer of that card can't inherit a bet the user never made for it."""
    _pending.pop(cid, None)


def clear_all_pending() -> None:
    """Drop every pending confidence. Used when the Reviewer is closing, so no
    stash survives to be mis-attached to a future session's answer."""
    _pending.clear()


def clear_pending_for_note(col: Collection, nid: int) -> None:
    """Drop pending confidences for all cards of a note. The note-level
    bury/suspend hooks pass a NOTE id, but ``_pending`` is keyed by CARD id, so
    resolve the note's cards and clear each. Best-effort: a missing note (e.g.
    already deleted) is a harmless no-op."""
    try:
        card_ids = col.get_note(nid).card_ids()
    except Exception:
        return
    for cid in card_ids:
        _pending.pop(cid, None)


def is_question_state(state: Any) -> bool:
    """True iff the Reviewer is showing the QUESTION side. A confidence is a
    PRE-answer bet, so we only accept it on ``"question"`` — never on
    ``"answer"``/``"transition"``/``None``. This stops the qfmt buttons (which
    re-render on the answer side via ``{{FrontSide}}``) from overwriting the
    genuine pre-answer confidence after the answer is revealed."""
    return state == "question"


def build_attempt(
    cid: int, revlog_id: int, level: str, ease: int, ts: int
) -> dict[str, Any]:
    """Pure builder for one calibration attempt entry. ``correct`` is the
    SELF-RATED outcome (ease >= 3), matching the engine's honesty rule."""
    return {
        "cid": cid,
        "revlog_id": revlog_id,
        "level": level,
        "correct": ease >= 3,
        "ts": ts,
    }


def append_attempt(col: Collection, attempt: dict[str, Any]) -> None:
    """Append one attempt to the config-blob log, deduped by (cid, revlog_id).
    A light Speedrun-owned config write (mirrors the other speedrun:* writes);
    touches no cards/notes/scheduling. Idempotent on a repeated key."""
    log = col.get_config(CALIBRATION_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
    key = (attempt["cid"], attempt["revlog_id"])
    if any((e.get("cid"), e.get("revlog_id")) == key for e in log):
        return
    log.append(attempt)
    col.set_config(CALIBRATION_LOG_KEY, log)


def answer_revlog_id(col: Collection, cid: int) -> Optional[int]:
    """The newest revlog id for a card — the id of the answer that just fired.
    ``reviewer_did_answer_card`` runs after the answer op persists, so this is a
    stable dedupe key. None if (unexpectedly) no revlog row exists."""
    return col.db.scalar(
        "SELECT id FROM revlog WHERE cid = ? ORDER BY id DESC LIMIT 1", cid
    )


def reconcile_answer(col: Collection, cid: int, ease: int) -> Optional[dict[str, Any]]:
    """Consume any pending confidence for ``cid`` and write the attempt. Returns
    the written attempt (for tests) or None when there was nothing pending / no
    revlog row. Pure w.r.t. Qt; safe to call with a real Collection."""
    level = take_pending(cid)
    if level is None:
        return None
    revlog_id = answer_revlog_id(col, cid)
    if revlog_id is None:
        return None
    attempt = build_attempt(cid, revlog_id, level, ease, int(time.time()))
    append_attempt(col, attempt)
    return attempt


# ---- Qt wiring (the only Qt-touching code) --------------------------------


def _on_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    import aqt.reviewer

    if handled[0]:
        return handled
    level = parse_conf_message(message)
    if level is None:
        return handled
    # Only capture in the Reviewer, and only on Speedrun::Problem cards.
    if not isinstance(context, aqt.reviewer.Reviewer):
        return handled
    # Only accept a PRE-answer bet: the qfmt confidence buttons re-render on the
    # answer side ({{FrontSide}}), so a post-reveal click must not overwrite the
    # genuine question-side confidence.
    if not is_question_state(context.state):
        return handled
    card = context.card
    if not is_problem_card(card):
        return handled
    stash_pending(card.id, level)
    return (True, None)


def _on_answer(reviewer: aqt.reviewer.Reviewer, card: Card, ease: int) -> None:
    if not is_problem_card(card):
        # Clear any stray pending for this card without writing.
        take_pending(card.id)
        return
    try:
        reconcile_answer(reviewer.mw.col, card.id, ease)
    except Exception:
        # Capture is best-effort; never break the answer flow on a logging error.
        take_pending(card.id)


def _on_will_suspend_card(cid: int) -> None:
    # reviewer_will_suspend_card(id: int) — the current card's id.
    clear_pending(cid)


def _on_will_bury_card(cid: int) -> None:
    # reviewer_will_bury_card(id: int) — the current card's id.
    clear_pending(cid)


def _on_will_suspend_note(nid: int) -> None:
    # reviewer_will_suspend_note(nid: int) — a NOTE id; clear all its cards.
    from aqt import mw

    if mw is not None and mw.col is not None:
        clear_pending_for_note(mw.col, nid)


def _on_will_bury_note(nid: int) -> None:
    # reviewer_will_bury_note(nid: int) — a NOTE id; clear all its cards.
    from aqt import mw

    if mw is not None and mw.col is not None:
        clear_pending_for_note(mw.col, nid)


def _on_will_end() -> None:
    # reviewer_will_end() — reviewer is closing; no stash may outlive it.
    clear_all_pending()


def register() -> None:
    """Wire the capture hooks. Called once at startup."""
    from aqt import gui_hooks

    gui_hooks.webview_did_receive_js_message.append(_on_js_message)
    gui_hooks.reviewer_did_answer_card.append(_on_answer)
    # BUG 5: clear a stale pending bet when a card is buried/suspended (so a
    # later answer can't inherit it) or when the reviewer closes.
    gui_hooks.reviewer_will_suspend_card.append(_on_will_suspend_card)
    gui_hooks.reviewer_will_bury_card.append(_on_will_bury_card)
    gui_hooks.reviewer_will_suspend_note.append(_on_will_suspend_note)
    gui_hooks.reviewer_will_bury_note.append(_on_will_bury_note)
    gui_hooks.reviewer_will_end.append(_on_will_end)
