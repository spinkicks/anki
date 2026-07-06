# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Desktop session timer for the Speedrun timed mini-mock.

Anki's built-in ``#time`` macro is PER-CARD (it resets every card), so a mock
that is meant to feel like a timed section has no visible whole-session clock.
This module injects a small fixed-position COUNT-UP ``mm:ss`` overlay into the
reviewer webview for the duration of a mini-mock, and tears it down when the
reviewer closes. It is HONEST: it shows elapsed wall-clock since the session
started — never a fabricated countdown.

Zero edits to ``reviewer.py`` (mirrors ``speedrun_capture``): three ``gui_hooks``
do the work.

* ``reviewer_did_init`` remembers the reviewer and clears any prior session (a
  fresh reviewer means a fresh clock).
* ``reviewer_did_show_question`` / ``reviewer_did_show_answer`` are where the
  overlay is (re)injected: the reviewer replaces the whole webview document on
  every card render (``stdHtml``), so a top-level ``<div>`` injected once would be
  wiped on the next card. We therefore re-inject on each render, but the SESSION
  START time is recorded ONCE (module-level) so the count-up is continuous across
  cards; a client-side ``setInterval`` keeps it ticking between renders. Injection
  is gated on the current deck's name starting with ``"Speedrun Mini-Mock"`` — a
  normal Start Run (the exam deck) never gets a timer.
* ``reviewer_will_end`` clears the interval, removes the overlay, and resets the
  session so the next mini-mock starts its clock from zero.

The deck-name gate predicate and the ``mm:ss`` formatting are pure, Qt-free
functions so they can be unit-tested without a live ``QApplication`` (see
``qt/tests/test_speedrun.py``). Only ``register()`` and the thin hook callbacks
touch Qt.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import aqt.reviewer
    from anki.cards import Card

# A mini-mock runs on the filtered deck built by
# ``speedrun_logic.build_mini_mock_deck``, named exactly "Speedrun Mini-Mock".
# We match by PREFIX because Anki auto-suffixes a duplicate filtered-deck name
# ("+", "++", …); any such variant is still a mini-mock and should be timed.
MINI_MOCK_DECK_PREFIX = "Speedrun Mini-Mock"

# DOM id of the injected overlay element, and the window-scoped handle of the
# tick interval. Well-known so a re-inject can clear the prior one (no dupes).
_OVERLAY_ID = "speedrun-mini-mock-timer"
_INTERVAL_HANDLE = "__speedrunMiniMockTimerInterval"

# Wall-clock (epoch seconds) when the current mini-mock session began, or None
# when no mock is running. Module-level: the reviewer is a singleton and the
# clock must persist across per-card re-renders.
_start_time: Optional[float] = None


def is_mini_mock_deck_name(name: str | None) -> bool:
    """True iff ``name`` is a Speedrun mini-mock deck (the only deck we time).

    Matches by prefix so an auto-suffixed duplicate ("Speedrun Mini-Mock+") is
    still recognised; a missing/blank name or any other deck is False."""
    if not name:
        return False
    return name.startswith(MINI_MOCK_DECK_PREFIX)


def format_mmss(elapsed_seconds: int) -> str:
    """Format an elapsed second count as ``mm:ss`` (count-UP, never negative).

    Minutes are NOT capped at 59 — a 65-minute session reads "65:00", not
    "05:00" — because this is honest elapsed time, not a wall clock. A negative
    input (clock skew) clamps to "00:00" rather than showing a bogus value."""
    total = int(elapsed_seconds)
    if total < 0:
        total = 0
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


# ---- Qt wiring (the only Qt-touching code) --------------------------------


def _current_deck_name(reviewer: aqt.reviewer.Reviewer) -> str | None:
    """The current deck's name, or None if it can't be read (never crash)."""
    try:
        return reviewer.mw.col.decks.current()["name"]
    except Exception:
        return None


def _overlay_js(start_ms: int) -> str:
    """JS that (re)installs the fixed-position count-up overlay in the reviewer
    webview. Clears any prior interval/overlay first (so a re-inject on the next
    card can't stack duplicates), then ticks ``mm:ss`` every 500ms from a fixed
    session start. Pure elapsed = now - start; never a countdown."""
    return f"""
(function() {{
  try {{
    if (window.{_INTERVAL_HANDLE}) {{
      clearInterval(window.{_INTERVAL_HANDLE});
      window.{_INTERVAL_HANDLE} = null;
    }}
    var existing = document.getElementById("{_OVERLAY_ID}");
    if (existing) {{ existing.remove(); }}
    var el = document.createElement("div");
    el.id = "{_OVERLAY_ID}";
    el.style.cssText = "position:fixed;top:8px;right:12px;z-index:2147483647;"
      + "font:600 15px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;"
      + "padding:4px 10px;border-radius:8px;pointer-events:none;"
      + "background:rgba(30,30,30,0.82);color:#fff;"
      + "box-shadow:0 1px 4px rgba(0,0,0,0.3);";
    el.setAttribute("aria-label", "Mini-mock elapsed time");
    document.body.appendChild(el);
    var start = {start_ms};
    function fmt(totalSec) {{
      if (totalSec < 0) totalSec = 0;
      var m = Math.floor(totalSec / 60);
      var s = totalSec % 60;
      return (m < 10 ? "0" + m : "" + m) + ":" + (s < 10 ? "0" + s : "" + s);
    }}
    function tick() {{
      var e = document.getElementById("{_OVERLAY_ID}");
      if (!e) return;
      var elapsed = Math.floor((Date.now() - start) / 1000);
      e.textContent = "⏱ " + fmt(elapsed);
    }}
    tick();
    window.{_INTERVAL_HANDLE} = setInterval(tick, 500);
  }} catch (err) {{ /* overlay is best-effort; never break the reviewer */ }}
}})();
"""


def _teardown_js() -> str:
    """JS that stops the tick and removes the overlay."""
    return f"""
(function() {{
  try {{
    if (window.{_INTERVAL_HANDLE}) {{
      clearInterval(window.{_INTERVAL_HANDLE});
      window.{_INTERVAL_HANDLE} = null;
    }}
    var el = document.getElementById("{_OVERLAY_ID}");
    if (el) {{ el.remove(); }}
  }} catch (err) {{}}
}})();
"""


def _maybe_show_timer(reviewer: aqt.reviewer.Reviewer) -> None:
    """(Re)inject the overlay when the current deck is a mini-mock, recording the
    session start ONCE so the count-up is continuous across card re-renders."""
    global _start_time
    if not is_mini_mock_deck_name(_current_deck_name(reviewer)):
        return
    if _start_time is None:
        _start_time = time.time()
    try:
        reviewer.web.eval(_overlay_js(int(_start_time * 1000)))
    except Exception:
        # The timer is a cosmetic overlay; a webview error must never break the
        # reviewer's own render.
        pass


def _reset_timer(reviewer: Optional[aqt.reviewer.Reviewer] = None) -> None:
    """Tear down the overlay and forget the session start."""
    global _start_time
    _start_time = None
    if reviewer is None:
        from aqt import mw

        reviewer = mw.reviewer if mw is not None else None
    if reviewer is None:
        return
    try:
        reviewer.web.eval(_teardown_js())
    except Exception:
        pass


def _on_did_init(reviewer: aqt.reviewer.Reviewer) -> None:
    # A fresh reviewer means a fresh session: drop any stale start time so the
    # next mini-mock's clock begins at zero.
    global _start_time
    _start_time = None


def _on_show_question(card: Card) -> None:
    from aqt import mw

    if mw is not None and mw.reviewer is not None:
        _maybe_show_timer(mw.reviewer)


def _on_show_answer(card: Card) -> None:
    from aqt import mw

    if mw is not None and mw.reviewer is not None:
        _maybe_show_timer(mw.reviewer)


def _on_will_end() -> None:
    # Reviewer is closing: stop the clock and remove the overlay so it can't
    # linger, and so the next mini-mock starts fresh.
    _reset_timer()


def register() -> None:
    """Wire the mini-mock timer hooks. Called once at startup."""
    from aqt import gui_hooks

    gui_hooks.reviewer_did_init.append(_on_did_init)
    gui_hooks.reviewer_did_show_question.append(_on_show_question)
    gui_hooks.reviewer_did_show_answer.append(_on_show_answer)
    gui_hooks.reviewer_will_end.append(_on_will_end)
