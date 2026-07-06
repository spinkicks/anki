# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import aqt
import aqt.main
from aqt.qt import *
from aqt.speedrun_logic import EXAM_DECK_NAME
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView, AnkiWebViewKind


def _speedrun_single_window_enabled(mw: aqt.main.AnkiQt) -> bool:
    """Read the reversible phase-2 one-window flag (default ON).

    Mirrors the existing Speedrun config-flag pattern (e.g. how
    ``speedrunSeedImportEnabled`` is read in main.py). Any failure to read the
    profile disables the behaviour, so the safe default on error is the classic
    phase-1 window (parented to ``mw``, base window never touched)."""
    try:
        return bool(mw.pm.profile.get("speedrunSingleWindow", True))
    except Exception:
        return False


class SpeedrunWindow(QDialog):
    """The single Speedrun window (Home / The Map / Memory in ONE webview).

    Speedrun used to be TWO top-level QDialog windows — SpeedrunHome and
    SpeedrunMemory — registered under two ``aqt.dialogs`` keys, so Home and Memory
    could both be open at once (up to three windows: main + Home + Memory). The
    Svelte side is already ONE SPA (the persistent SpeedrunShell sidebar links
    Home / Map / Memory), so the split was pure desktop-window duplication. This
    class collapses them into ONE window under a SINGLE registry key ("Speedrun")
    with one webview + one geometry. Navigating between Home / Map / Memory
    (whether via the in-page sidebar or via the Tools menu) reuses THIS window and
    just loads the target SvelteKit page — never a second window.

    It hosts a SvelteKit page in the persistent sidebar shell, which shows the
    Practice actions (Start Run / Mini-mock) and the AI "Generate practice" button
    on EVERY page and fires them via ``(pycmd ?? bridgeCommand)(cmd)``. On desktop
    the webview always has ``pycmd`` (Qt injects it globally), so those buttons act
    on every page. There is a SINGLE ``set_bridge_command`` wiring, so the desktop
    pycmd===bridgeCommand alias can't become a double-dispatch."""

    # ``DIALOG_NAME`` is BOTH the aqt.dialogs registry key and the geometry-save
    # key. It intentionally does NOT equal the class name (which the old two-class
    # design relied on for markClosed): the single key is "Speedrun".
    DIALOG_NAME = "Speedrun"
    WINDOW_TITLE = "Speedrun"
    DEFAULT_SIZE = (1000, 820)

    # The SvelteKit pages the one window can show. A "route" passed to open/reopen
    # is one of these page names; navigation loads it into the same webview.
    HOME_PAGE = "speedrun-home"
    MAP_PAGE = "speedrun-map"
    MEMORY_PAGE = "speedrun-memory"

    def __init__(
        self, mw: aqt.main.AnkiQt, route: str = HOME_PAGE
    ) -> None:
        # Phase-2 one-window UX (reversible via ``speedrunSingleWindow``, default
        # ON): when enabled, do NOT parent this window to ``mw``. Minimizing
        # ``mw`` (to hide the base app so Speedrun feels like a single cohesive
        # app) must NOT cascade-minimize THIS window — on Windows a parented
        # top-level shares its parent's taskbar entry and minimizes WITH it — and
        # an unparented top-level keeps its OWN taskbar entry, so the app can never
        # be stranded with no visible/taskbar window. ``self.mw`` still drives ALL
        # logic. Flag OFF => classic phase-1 (parented to mw; base never touched).
        single_window = _speedrun_single_window_enabled(mw)
        QDialog.__init__(
            self, None if single_window else mw, Qt.WindowType.Window
        )
        mw.garbage_collect_on_dialog_finish(self)
        self.mw = mw
        self._single_window = single_window
        # True once we have asked the base window to minimize; gates the
        # guaranteed restore so we only ever un-minimize a window WE minimized.
        self._did_minimize_base = False
        self.name = self.DIALOG_NAME
        self.setWindowTitle(self.WINDOW_TITLE)
        disable_help_button(self)
        self.web = AnkiWebView(kind=AnkiWebViewKind.SPEEDRUN)
        self.web.set_bridge_command(self._on_bridge_cmd, self)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.setLayout(layout)
        restoreGeom(self, self.name, default_size=self.DEFAULT_SIZE)
        self._current_page = route or self.HOME_PAGE
        self.web.load_sveltekit_page(self._current_page)
        self.show()
        # Minimize the base window only AFTER this window is shown — never earlier
        # in construction in a way that could race the post-sync startup dialog
        # (the startup auto-open already fires post-sync). Guarded + once-only so
        # it can never crash launch or leave the app with no visible window.
        self._minimize_base_window()

    def reopen(self, _mw: aqt.main.AnkiQt, route: str = HOME_PAGE) -> None:
        """Second+ ``dialogs.open("Speedrun", ...)`` call: the DialogManager has
        already raised/activated this one window; here we ONLY navigate its webview
        — and only when the requested route differs from the page already shown
        (so Tools->Home while Home is open is a pure raise, while Tools->Memory
        reuses this window and navigates). Never spawns a second window."""
        self._navigate(route or self.HOME_PAGE)

    def _navigate(self, route: str) -> None:
        """Load ``route`` into THIS webview, but only if it isn't already shown."""
        if route == self._current_page:
            return
        self._current_page = route
        self.web.load_sveltekit_page(route)

    # ---- Phase-2 single-window: minimize/restore the base main window --------

    def _minimize_base_window(self) -> None:
        """Minimize the base main window so the open Speedrun window feels like a
        single cohesive app.

        Uses ``showMinimized()`` — NEVER ``hide()`` — so the base window always
        keeps a taskbar entry and the app can never be stranded with no
        visible/taskbar window. Runs at most once (so raising/re-showing this
        window later does not repeatedly yank the base window down) and only when
        the reversible single-window flag is on. Fully guarded: a failure to
        minimize can never crash launch."""
        if self._did_minimize_base or not self._single_window:
            return
        # Mark BEFORE the call so that even if it raises, the paired restore in
        # every exit path still runs (never leave the base window minimized).
        self._did_minimize_base = True
        try:
            self.mw.showMinimized()
        except Exception:
            pass

    def _restore_base_window(self) -> None:
        """GUARANTEED restore of the base main window, called on EVERY Speedrun
        exit path (user close/reject and route-to-reviewer).

        Only un-minimizes a window we actually minimized, and is fully guarded so
        it can never raise into an exit/launch path or leave the app with no
        visible window. ``showNormal`` + ``raise_`` + ``activateWindow`` so the
        base window (which hosts the reviewer) is visible and focused again."""
        if not self._did_minimize_base:
            return
        try:
            self.mw.showNormal()
            self.mw.raise_()
            self.mw.activateWindow()
        except Exception:
            pass

    # The exam deck the run studies. Grounded fact: this is the seed deck name.
    # Single source of truth lives in speedrun_logic (shared with the installer
    # seed auto-import idempotency check).
    EXAM_DECK = EXAM_DECK_NAME
    # The Problems subdeck a timed mini-mock draws from (seeded bank).
    PROBLEM_DECK = "Speedrun::GRE Math::Problems"

    def _on_bridge_cmd(self, cmd: str) -> Any:
        if cmd == "startrun:import":
            self._import_deck()
        elif cmd == "startrun:customstudy":
            self._custom_study()
        elif cmd == "startrun" or cmd.startswith("startrun:"):
            self._start_run()
        elif cmd == "minimock":
            self._start_mini_mock()
        elif cmd == "open:memory":
            # Legacy 2nd-window spawn removed: navigate the SAME webview to the
            # Memory page (one window). The in-page SPA sidebar links already do
            # client-side nav; this handler covers any remaining bridge callers.
            self._navigate(self.MEMORY_PAGE)
        # AI "Generate practice" (The Map lives in this same webview via the
        # SvelteKit /speedrun-map link, so it shares this bridge). Both handlers
        # are inert unless the external AI service is enabled+reachable, so the
        # app's behaviour is UNCHANGED when AI is off.
        elif cmd == "speedrun:ai:probe":
            self._ai_probe()
        elif cmd.startswith("speedrun:gen:"):
            self._ai_generate(cmd[len("speedrun:gen:") :])
        return False

    # ---- AI "Generate practice" (The Map) ---------------------------------

    def _ai_probe(self) -> None:
        """Answer the Map's on-mount availability probe. Runs the env check + a
        short /health GET OFF the UI thread, then pushes the boolean back to the
        page via ``window.speedrunAiAvailability``. Unreachable/timeout/off =>
        false => the button stays disabled (zero behaviour change)."""
        from aqt import speedrun_ai
        from aqt.operations import QueryOp

        def op(_col: Any) -> bool:
            return speedrun_ai.is_ai_available()

        def done(available: bool) -> None:
            self.web.eval(
                "window.speedrunAiAvailability"
                f" && window.speedrunAiAvailability({str(bool(available)).lower()});"
            )

        # Availability is a pure network/env check — it does not touch the
        # collection, so allow it to run without serialising on the col.
        QueryOp(
            parent=self, op=op, success=done
        ).without_collection().run_in_background()

    def _ai_generate(self, topic: str) -> None:
        """Handle ``speedrun:gen:<topic_id>``: POST /generate_batch OFF the UI
        thread, import ONLY the verified problems it returns, then push
        ``{added, topic}`` (or an error) back to the page via
        ``window.speedrunGenStatus``. Timeouts/connection errors degrade to an
        error callback — never a crash."""
        from aqt import speedrun_ai
        from aqt.operations import QueryOp

        topic = (topic or "").strip()
        if not topic:
            return

        def op(col: Any) -> dict[str, Any]:
            # run_generate does the network fetch AND the (undoable) import; it
            # needs the collection for add_note, so this QueryOp uses the col.
            return speedrun_ai.run_generate(col, topic)

        def done(result: dict[str, Any]) -> None:
            payload = json.dumps(
                {
                    "topic": result.get("topic", topic),
                    "added": int(result.get("added", 0)),
                    "error": result.get("error", ""),
                }
            )
            self.web.eval(
                f"window.speedrunGenStatus && window.speedrunGenStatus({payload});"
            )

        def failed(exc: Exception) -> None:
            payload = json.dumps({"topic": topic, "added": 0, "error": str(exc)})
            self.web.eval(
                f"window.speedrunGenStatus && window.speedrunGenStatus({payload});"
            )

        QueryOp(parent=self, op=op, success=done).failure(failed).with_progress(
            "Generating… (verifying + grounding)"
        ).run_in_background()

    def _start_run(self) -> None:
        # Launch REAL study on the exam deck. When it can't (deck missing, or
        # nothing due), tell the user why IN our page via an honest banner —
        # never leave them at the bare Anki "Congratulations" deck-browser
        # dead-end that "overview" produces on a fresh/empty collection.
        # The decision (which relies on the SCHEDULER's due counts, not the
        # count-less structural deck tree) lives in speedrun_logic so it can be
        # unit-tested without Qt; see qt/tests/test_speedrun.py.
        from aqt.speedrun_logic import decide_start_run

        decision = decide_start_run(self.mw.col, self.EXAM_DECK)
        if decision.status == "importNeeded":
            self.web.eval(
                "window.speedrunStartStatus"
                ' && window.speedrunStartStatus("importNeeded");'
            )
        elif decision.status == "caughtUp":
            self.web.eval(
                "window.speedrunStartStatus"
                f' && window.speedrunStartStatus("caughtUp", {int(decision.new_left)});'
            )
        else:  # "ready" — cards are due; launch the reviewer on the exam deck.
            assert decision.deck_id is not None
            self.mw.col.decks.select(decision.deck_id)
            self.close()
            # The reviewer runs in the BASE window, so it MUST be visible there —
            # restore it (guaranteed) right before entering the review state.
            self._restore_base_window()
            self.mw.moveToState("review")

    def _start_mini_mock(self) -> None:
        # Launch a TIMED mini-mock: a filtered deck of random problems over the
        # Problems subdeck. Per-answer wall-clock is captured automatically in
        # revlog.taken_millis (no engine change). Size is config-driven
        # (Decision 13 default 10; synced col config), never hard-coded here.
        # The build sets reschedule=True so attempts feed Performance + the
        # Readiness give-up counter (see build_mini_mock_deck's docstring for the
        # is_cramming() exclusion this avoids). Decision logic is Qt-free and
        # unit-tested in qt/tests/test_speedrun.py.
        # Android note: Android gets the same problem bank via the seed .apkg and
        # studies the Problems subdeck through its native reviewer; a bespoke
        # Android timed mini-mock UI is DEFERRED this cycle (no anki-android code).
        from aqt.speedrun_logic import (
            build_mini_mock_deck,
            decide_mini_mock,
            resolve_mini_mock_size,
        )

        # Resolve the config value defensively (defense-in-depth; build_mini_mock_deck
        # also clamps): a 0/negative size would make the filtered-deck search-term
        # limit=0, pulling zero cards -> FilteredDeckError -> the launch crashes; and
        # a PRESENT-but-bad synced value (JSON null / "abc" / "7.5") would make a bare
        # int(...) raise before the clamp. resolve_mini_mock_size coerces + clamps
        # without ever raising.
        size = resolve_mini_mock_size(self.mw.col)
        decision = decide_mini_mock(self.mw.col, self.PROBLEM_DECK)
        if decision.status == "importNeeded":
            self.web.eval(
                "window.speedrunStartStatus"
                ' && window.speedrunStartStatus("importNeeded");'
            )
        elif decision.status == "noActiveProblems":
            # Bank imported but every problem card is suspended: telling the user
            # to import would be dishonest — the honest fix is to UNSUSPEND. Fire
            # a distinct status so the page shows the unsuspend banner.
            self.web.eval(
                "window.speedrunStartStatus"
                ' && window.speedrunStartStatus("noActiveProblems");'
            )
        else:  # "ready" — build the filtered deck and launch the reviewer.
            # The build can still fail honestly (e.g. every matching problem card
            # got suspended between decide and build -> SearchReturnedNoCards).
            # Surface that IN our page via the same banner mechanism instead of
            # letting an uncaught exception crash the launch. Never fake success.
            try:
                did = build_mini_mock_deck(self.mw.col, self.PROBLEM_DECK, size)
            except Exception:
                self.web.eval(
                    "window.speedrunStartStatus"
                    ' && window.speedrunStartStatus("mockFailed");'
                )
                return
            self.mw.col.decks.select(did)
            self.close()
            # Reviewer runs in the BASE window — restore it before entering review.
            self._restore_base_window()
            self.mw.moveToState("review")

    def _import_deck(self) -> None:
        # Open Anki's generic File>Import dialog (prompt_for_file_then_import).
        # We do NOT hardcode the seed .apkg path because it may not exist on a
        # user's machine; the generic picker is the honest, robust in-app flow.
        self.mw.onImport()

    def _custom_study(self) -> None:
        # Select the exam deck (Custom Study operates on the *current* deck via
        # decks.get_current_id) then open Anki's real Custom Study dialog.
        did = self.mw.col.decks.id_for_name(self.EXAM_DECK)
        if did is None:
            self.web.eval(
                "window.speedrunStartStatus"
                ' && window.speedrunStartStatus("importNeeded");'
            )
            return
        self.mw.col.decks.select(did)
        from aqt.customstudy import CustomStudy

        CustomStudy.fetch_data_and_show(self.mw)

    def reject(self) -> None:
        # Guaranteed restore FIRST: whatever happens during teardown below, the
        # base window must never be left minimized because Speedrun closed (no-op
        # unless we actually minimized it).
        self._restore_base_window()
        self.web.cleanup()
        saveGeom(self, self.name)
        # Single registry key: mark the one "Speedrun" dialog closed (self.name
        # == DIALOG_NAME == the aqt.dialogs key, no longer the class name).
        aqt.dialogs.markClosed(self.name)
        QDialog.reject(self)

    def closeWithCallback(self, callback: Callable[[], None]) -> None:
        self.reject()
        callback()
