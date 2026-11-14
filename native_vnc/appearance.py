# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compact, neutral system styling shared by the form and window controls."""

from PySide6.QtGui import QColor, QFont, QPalette


def interface_font():
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    font.setPointSizeF(9)
    return font


def apply_appearance(window, dark):
    if dark:
        colors = dict(background="#202020", surface="#2b2b2b", text="#eeeeee",
                      muted="#aaaaaa", border="#505050", hover="#383838", disabled="#777777")
    else:
        colors = dict(background="#f3f3f3", surface="#ffffff", text="#202020",
                      muted="#666666", border="#b8b8b8", hover="#e5e5e5", disabled="#999999")
    palette = QPalette(window.palette())
    for role, color in ((QPalette.ColorRole.Window, "background"),
                        (QPalette.ColorRole.Base, "surface"),
                        (QPalette.ColorRole.Button, "surface"),
                        (QPalette.ColorRole.WindowText, "text"),
                        (QPalette.ColorRole.Text, "text"),
                        (QPalette.ColorRole.ButtonText, "text"),
                        (QPalette.ColorRole.PlaceholderText, "muted")):
        palette.setColor(role, QColor(colors[color]))
    window.setStyleSheet("""
        QMainWindow, QDialog, QWidget#start { background: %(background)s; }
        QLabel, QCheckBox { color: %(text)s; }
        QLabel#appTitle { font-size: 20px; font-weight: 600; margin: 0; padding: 0; }
        QLabel#startStatus { color: %(muted)s; font-size: 11px; }
        QLineEdit { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s;
                    border-radius: 4px; padding: 5px 8px; min-height: 19px; }
        QLineEdit:focus { border-color: palette(highlight); }
        QPushButton { background: transparent; color: %(text)s; border: none;
                      border-radius: 4px; padding: 5px 12px; }
        QPushButton:hover { background: %(hover)s; }
        QPushButton:pressed { background: %(border)s; }
        QPushButton:disabled { color: %(disabled)s; }
        QPushButton:focus { color: palette(highlight); }
        QPushButton#connect { background: %(surface)s; min-height: 22px;
                              font-size: 16px; }
        QPushButton#connect:hover { background: %(hover)s; }
        QPushButton#settings { padding: 0 8px; font-size: 12px; }
        QCheckBox { spacing: 6px; }
        QWidget#connectionOverlay { background: %(surface)s; border: 1px solid %(border)s;
                                   border-radius: 2px; }
        QLabel#connectionMessage { color: %(text)s; font-size: 13px; }
    """ % colors)
    # Apply after stylesheet repolishing, which otherwise restores the old palette.
    window.setPalette(palette)
    window.centralWidget().setPalette(palette)
