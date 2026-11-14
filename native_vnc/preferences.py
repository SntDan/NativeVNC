# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Small preferences dialog; changes are committed only when saved."""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QSpinBox, QVBoxLayout,
)

from .i18n import LANGUAGES, translate


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
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
        self.scroll_label = QLabel()
        self.scroll_multiplier = QSpinBox()
        self.scroll_multiplier.setRange(1, 100)
        self.scroll_multiplier.setSuffix("×")
        self.scroll_multiplier.setValue(settings.mac_scroll_multiplier)
        form.addRow(self.scroll_label, self.scroll_multiplier)
        layout.addLayout(form)
        self.reverse_scroll = QCheckBox()
        self.reverse_scroll.setChecked(settings.reverse_scroll)
        layout.addWidget(self.reverse_scroll)
        self.remember_window = QCheckBox()
        self.remember_window.setChecked(settings.remember_window_size)
        layout.addWidget(self.remember_window)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.setObjectName("settingsButtons")
        self.buttons.setCenterButtons(True)
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
        self.scroll_label.setText(translate("Mac 滚轮速度", language))
        self.scroll_multiplier.setAccessibleName(self.scroll_label.text())
        self.scroll_multiplier.setToolTip(translate(
            "仅用于 Mac 屏幕共享，默认 50×。若终端等应用滚动过快，可调低；1× 为原始速度。", language))
        self.reverse_scroll.setText(translate("反转滚轮方向", language))
        self.reverse_scroll.setToolTip(translate("默认关闭；开启后反转所有连接的横向和纵向滚动。", language))
        self.remember_window.setText(translate("记忆上次窗口大小", language))
        self.remember_window.setToolTip(translate("仅影响普通窗口的尺寸和位置，仍会记忆最大化和全屏状态。", language))
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(translate("保存", language))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(translate("取消", language))

    def accept(self):
        try:
            self.settings.set_preferences(self.language.currentData(), self.remember_window.isChecked(),
                                          self.scroll_multiplier.value(), self.reverse_scroll.isChecked())
        except OSError as exc:
            message = translate("无法保存设置：{error}", self.language.currentData()).format(error=exc)
            QMessageBox.warning(self, self.windowTitle(), message)
            return
        super().accept()
