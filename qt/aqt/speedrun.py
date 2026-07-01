# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from __future__ import annotations

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
