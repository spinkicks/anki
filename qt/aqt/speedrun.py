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


class _SpeedrunBridgeDialog(QDialog):
    """Shared base for the Speedrun webview dialogs (Home and Memory).

    Both host a SvelteKit page in the SAME persistent sidebar shell, which shows
    the Practice actions (Start Run / Mini-mock) and the AI "Generate practice"
    button on EVERY page and fires them via ``(pycmd ?? bridgeCommand)(cmd)``. On
    desktop the webview always has ``pycmd`` (Qt injects it globally), so those
    buttons render ENABLED on Memory too — they must therefore ACT, not no-op.

    So the bridge-command wiring (``set_bridge_command``) + ``_on_bridge_cmd``
    dispatch + all the action methods live here, shared by both subclasses. Each
    subclass supplies only its own registry name / geometry key, window title,
    SvelteKit page and default size (via class attributes below). Keeping the
    wiring in ONE place also guarantees the desktop pycmd===bridgeCommand alias
    can't be turned into a double-dispatch: there is a single set_bridge_command
    call, inherited by both dialogs."""

    # Subclasses override these four. ``DIALOG_NAME`` is BOTH the aqt.dialogs
    # registry key and the geometry-save key, so it must match the name the class
    # is registered under in aqt/__init__.py (which equals the class name).
    DIALOG_NAME = ""
    WINDOW_TITLE = ""
    SVELTE_PAGE = ""
    DEFAULT_SIZE = (1000, 820)

    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        mw.garbage_collect_on_dialog_finish(self)
        self.mw = mw
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
        self.web.load_sveltekit_page(self.SVELTE_PAGE)
        self.show()

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
            aqt.dialogs.open("SpeedrunMemory", self.mw)
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
        self.web.cleanup()
        saveGeom(self, self.name)
        # The aqt.dialogs registry key equals the concrete class name
        # (SpeedrunHome / SpeedrunMemory), so mark THIS dialog closed.
        aqt.dialogs.markClosed(type(self).__name__)
        QDialog.reject(self)

    def closeWithCallback(self, callback: Callable[[], None]) -> None:
        self.reject()
        callback()


class SpeedrunHome(_SpeedrunBridgeDialog):
    DIALOG_NAME = "speedrunHome"
    WINDOW_TITLE = "Speedrun: Home"
    SVELTE_PAGE = "speedrun-home"
    DEFAULT_SIZE = (1000, 820)


class SpeedrunMemory(_SpeedrunBridgeDialog):
    # Same bridge handling as Home (inherited): the merged sidebar shows the
    # Practice/Generate actions on the Memory page too, so they must ACT here —
    # previously SpeedrunMemory never wired set_bridge_command and the buttons
    # no-op'd. Only the page/title/geometry differ.
    DIALOG_NAME = "speedrunMemory"
    WINDOW_TITLE = "Speedrun: Memory"
    SVELTE_PAGE = "speedrun-memory"
    DEFAULT_SIZE = (900, 800)
