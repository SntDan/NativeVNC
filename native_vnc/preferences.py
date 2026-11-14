# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Small preferences dialog; changes are committed only when saved."""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QVBoxLayout,
)

from .i18n import LANGUAGES, translate


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        form = QFormLayout()
        self.language_label = QLabel()
        self.language = QComboBox()
        for label, code in LANGUAGES:
            self.language.addItem(label, code)
        self.language.setCurrentIndex(self.language.findData(settings.language))
        form.addRow(self.language_label, self.language)
        layout.addLayout(form)
        self.remember_window = QCheckBox()
        self.remember_window.setMinimumHeight(24)
        self.remember_window.setChecked(settings.remember_window_size)
        layout.addWidget(self.remember_window)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.language.currentIndexChanged.connect(self.update_language)
        self.update_language()

    def update_language(self, index=None):
        language = self.language.currentData()
        self.setWindowTitle(translate("设置", language))
        self.language_label.setText(translate("语言", language))
        self.language.setAccessibleName(self.language_label.text())
        self.remember_window.setText(translate("记忆上次窗口大小", language))
        self.remember_window.setToolTip(translate("仅影响普通窗口的尺寸和位置，仍会记忆最大化和全屏状态。", language))
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(translate("保存", language))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(translate("取消", language))

    def accept(self):
        try:
            self.settings.set_preferences(self.language.currentData(), self.remember_window.isChecked())
        except OSError as exc:
            message = translate("无法保存设置：{error}", self.language.currentData()).format(error=exc)
            QMessageBox.warning(self, self.windowTitle(), message)
            return
        super().accept()
