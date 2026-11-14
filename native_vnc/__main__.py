# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Native VNC")
    app.setOrganizationName("NativeVNC")
    window = MainWindow()
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
