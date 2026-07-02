# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import aqt
import aqt.main
from aqt.qt import *
from aqt.utils import disable_help_button, restoreGeom, saveGeom
from aqt.webview import AnkiWebView, AnkiWebViewKind


class SpeedrunMemory(QDialog):
    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        mw.garbage_collect_on_dialog_finish(self)
        self.mw = mw
        self.name = "speedrunMemory"
        self.setWindowTitle("Speedrun: Memory")
        disable_help_button(self)
        self.web = AnkiWebView(kind=AnkiWebViewKind.SPEEDRUN)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.setLayout(layout)
        restoreGeom(self, self.name, default_size=(900, 800))
        self.web.load_sveltekit_page("speedrun-memory")
        self.show()

    def reject(self) -> None:
        self.web.cleanup()
        saveGeom(self, self.name)
        aqt.dialogs.markClosed("SpeedrunMemory")
        QDialog.reject(self)

    def closeWithCallback(self, callback: Callable[[], None]) -> None:
        self.reject()
        callback()


class SpeedrunHome(QDialog):
    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        mw.garbage_collect_on_dialog_finish(self)
        self.mw = mw
        self.name = "speedrunHome"
        self.setWindowTitle("Speedrun: Home")
        disable_help_button(self)
        self.web = AnkiWebView(kind=AnkiWebViewKind.SPEEDRUN)
        self.web.set_bridge_command(self._on_bridge_cmd, self)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.setLayout(layout)
        restoreGeom(self, self.name, default_size=(1000, 820))
        self.web.load_sveltekit_page("speedrun-home")
        self.show()

    # The exam deck the run studies. Grounded fact: this is the seed deck name.
    EXAM_DECK = "Speedrun::GRE Math"

    def _on_bridge_cmd(self, cmd: str) -> Any:
        if cmd == "startrun:import":
            self._import_deck()
        elif cmd == "startrun:customstudy":
            self._custom_study()
        elif cmd == "startrun" or cmd.startswith("startrun:"):
            self._start_run()
        elif cmd == "open:memory":
            aqt.dialogs.open("SpeedrunMemory", self.mw)
        return False

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
        aqt.dialogs.markClosed("SpeedrunHome")
        QDialog.reject(self)

    def closeWithCallback(self, callback: Callable[[], None]) -> None:
        self.reject()
        callback()
