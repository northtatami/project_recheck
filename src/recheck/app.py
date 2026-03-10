from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from recheck.ui.main_window import RecheckMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Re:Check")
    app.setOrganizationName("ReCheck")
    window = RecheckMainWindow()
    window.show()
    return app.exec()
