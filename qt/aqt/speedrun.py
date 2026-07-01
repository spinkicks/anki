# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

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
        self.web = AnkiWebView(kind=AnkiWebViewKind.DEFAULT)
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


class SpeedrunHome(QDialog):
    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        QDialog.__init__(self, mw, Qt.WindowType.Window)
        mw.garbage_collect_on_dialog_finish(self)
        self.mw = mw
        self.name = "speedrunHome"
        self.setWindowTitle("Speedrun: Home")
        disable_help_button(self)
        self.web = AnkiWebView(kind=AnkiWebViewKind.DEFAULT)
        self.web.set_bridge_command(self._on_bridge_cmd, self)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.web)
        self.setLayout(layout)
        restoreGeom(self, self.name, default_size=(1000, 820))
        self.web.load_sveltekit_page("speedrun-home")
        self.show()

    def _on_bridge_cmd(self, cmd: str) -> Any:
        if cmd == "startrun" or cmd.startswith("startrun:"):
            self._start_run()
        elif cmd == "open:memory":
            aqt.dialogs.open("SpeedrunMemory", self.mw)
        return False

    def _start_run(self) -> None:
        # Use "overview" so Anki handles the graceful fallback: if no deck is
        # selected _overviewState redirects to deckBrowser automatically, and
        # if a deck *is* selected the user sees the deck overview (card count +
        # Study button) before entering the reviewer — safer than jumping
        # straight to "review" which can error when there are no due cards.
        self.close()
        self.mw.moveToState("overview")

    def reject(self) -> None:
        self.web.cleanup()
        saveGeom(self, self.name)
        aqt.dialogs.markClosed("SpeedrunHome")
        QDialog.reject(self)
