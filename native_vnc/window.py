# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Native resizable window and input forwarding. No embedded web engine."""

import threading

from PySide6.QtCore import QRect, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .protocol import Cancelled, Endpoint, ProtocolError, Session
from .appearance import apply_appearance, interface_font
from .i18n import translate
from .preferences import SettingsDialog
from .settings import Settings


KEYSYMS = {
    Qt.Key.Key_Backspace: 0xFF08, Qt.Key.Key_Tab: 0xFF09, Qt.Key.Key_Backtab: 0xFF09,
    Qt.Key.Key_Return: 0xFF0D, Qt.Key.Key_Enter: 0xFF0D, Qt.Key.Key_Escape: 0xFF1B,
    Qt.Key.Key_Insert: 0xFF63, Qt.Key.Key_Delete: 0xFFFF, Qt.Key.Key_Home: 0xFF50,
    Qt.Key.Key_End: 0xFF57, Qt.Key.Key_Left: 0xFF51, Qt.Key.Key_Up: 0xFF52,
    Qt.Key.Key_Right: 0xFF53, Qt.Key.Key_Down: 0xFF54, Qt.Key.Key_PageUp: 0xFF55,
    Qt.Key.Key_PageDown: 0xFF56, Qt.Key.Key_Shift: 0xFFE1, Qt.Key.Key_Control: 0xFFE3,
    Qt.Key.Key_Meta: 0xFFEB, Qt.Key.Key_Alt: 0xFFE9, Qt.Key.Key_AltGr: 0xFE03,
    Qt.Key.Key_CapsLock: 0xFFE5, Qt.Key.Key_NumLock: 0xFF7F,
    Qt.Key.Key_ScrollLock: 0xFF14, Qt.Key.Key_Print: 0xFF61, Qt.Key.Key_Pause: 0xFF13,
}
KEYSYMS.update({int(Qt.Key.Key_F1) + i: 0xFFBE + i for i in range(35)})


def keysym_for(event):
    if event.key() in KEYSYMS:
        return KEYSYMS[event.key()]
    text = event.text()
    if not text or ord(text[0]) < 32:
        key = event.key()
        if 32 <= key <= 126:
            text = chr(key)
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                text = text.lower()
        else:
            return None
    code = ord(text[0])
    return code if code <= 255 else 0x01000000 | code


class NetworkWorker(QThread):
    status = Signal(str)
    connected = Signal(str)
    frame = Signal()
    cursor = Signal(int, int, int, int, bytes)
    failed = Signal(str)

    def __init__(self, endpoint, password, parent=None, *, username=""):
        super().__init__(parent)
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.session = Session(endpoint, password, username=username, status=self.status.emit,
                               connected=self.connected.emit, frame=self.publish_frame,
                               cursor=self.cursor.emit)

    def publish_frame(self, width, height, pixels):
        with self.frame_lock:
            notify = self.latest_frame is None
            self.latest_frame = (width, height, pixels)
        # Only one notification can be pending; a busy UI skips obsolete frames.
        if notify:
            self.frame.emit()

    def take_frame(self):
        with self.frame_lock:
            frame = self.latest_frame
            self.latest_frame = None
        return frame

    def run(self):
        try:
            self.session.run()
        except Cancelled:
            pass
        except Exception as exc:
            if not self.session.stopped.is_set():
                # Some gateway errors contain the URL (and possibly a token).
                if isinstance(exc, ProtocolError):
                    self.failed.emit(str(exc))
                elif isinstance(exc, TimeoutError):
                    self.failed.emit("连接超时，请检查地址和网络。")
                else:
                    self.failed.emit("连接失败，请检查服务器、端口及证书。" + f"（{type(exc).__name__}）")


class RemoteView(QWidget):
    """Paint an aspect-fit framebuffer; inverse-map logical coordinates for RFB."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(1, 1)
        self.image = QImage()
        self._frame_pixels = b""
        self.session = None
        self.pressed = {}
        self.buttons = 0
        self.position = (0, 0)
        self.pending_move = None
        self.wheel_x = self.wheel_y = 0
        self.move_timer = QTimer(self)
        self.move_timer.setInterval(16)
        self.move_timer.setSingleShot(True)
        self.move_timer.timeout.connect(self.flush_move)
        self.message = ""
        self.panel = QWidget(self)
        self.panel.setObjectName("connectionOverlay")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(12)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setObjectName("connectionMessage")
        self.retry = QPushButton(translate("重新连接"))
        panel_layout.addWidget(self.message_label)
        panel_layout.addWidget(self.retry)
        self.panel.hide()

    def image_rect(self):
        if self.image.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRectF()
        scale = min(self.width() / self.image.width(), self.height() / self.image.height())
        width, height = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def remote_position(self, point, clamp=False):
        rect = self.image_rect()
        if rect.isEmpty() or (not clamp and not rect.contains(point)):
            return None
        x = int((point.x() - rect.x()) * self.image.width() / rect.width())
        y = int((point.y() - rect.y()) * self.image.height() / rect.height())
        return max(0, min(self.image.width() - 1, x)), max(0, min(self.image.height() - 1, y))

    def set_frame(self, width, height, pixels):
        self.image = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGB32)
        # Retain the immutable snapshot for the lifetime of the borrowed QImage buffer.
        self._frame_pixels = pixels
        self.update()

    def set_remote_cursor(self, width, height, x, y, pixels):
        if width and height:
            image = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
            self.setCursor(QCursor(QPixmap.fromImage(image), x, y))
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def show_message(self, message, retry=True):
        self.release_input()
        self.message = message
        self.message_label.setText(message)
        self.retry.setVisible(retry)
        self.panel.show()
        self.layout_panel()
        self.unsetCursor()
        self.update()

    def clear_message(self):
        self.message = ""
        self.panel.hide()
        self.update()

    def layout_panel(self):
        self.panel.setFixedWidth(min(380, max(200, self.width() - 32)))
        self.panel.adjustSize()
        self.panel.move((self.width() - self.panel.width()) // 2,
                        (self.height() - self.panel.height()) // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.image_rect()
        if rect.isEmpty() or rect.width() < self.width() or rect.height() < self.height():
            painter.fillRect(self.rect(), QColor("#151b23"))
        if not self.image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(rect, self.image)
        if self.message:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 155))

    def resizeEvent(self, event):
        if self.message:
            self.layout_panel()
        super().resizeEvent(event)

    def active(self):
        return self.session is not None and self.session.ready.is_set() and not self.message

    def flush_move(self):
        self.move_timer.stop()
        if self.pending_move and self.active():
            self.session.pointer(*self.pending_move, self.buttons)
        self.pending_move = None

    def mouseMoveEvent(self, event):
        if self.active():
            position = self.remote_position(event.position(), clamp=bool(self.buttons))
            if position is not None:
                self.position = position
                self.pending_move = position
                if not self.move_timer.isActive():
                    self.move_timer.start()

    @staticmethod
    def button_mask(buttons):
        return ((1 if buttons & Qt.MouseButton.LeftButton else 0) |
                (2 if buttons & Qt.MouseButton.MiddleButton else 0) |
                (4 if buttons & Qt.MouseButton.RightButton else 0))

    def mousePressEvent(self, event):
        if not self.active():
            return
        position = self.remote_position(event.position())
        if position is None:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.flush_move()
        self.position = position
        self.buttons = self.button_mask(event.buttons())
        self.session.pointer(*position, self.buttons)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.active() and self.buttons:
            self.flush_move()
            position = self.remote_position(event.position(), clamp=True)
            self.position = position or self.position
            self.buttons = self.button_mask(event.buttons())
            self.session.pointer(*self.position, self.buttons)
        event.accept()

    def wheelEvent(self, event):
        if not self.active():
            return
        position = self.remote_position(event.position())
        if position is None:
            return
        self.flush_move()
        self.position = position
        # Apple's server treats standard RFB wheel clicks as very small movements.
        # Scale before accumulating so high-resolution wheels retain small deltas.
        multiplier = self.settings.mac_scroll_multiplier if self.session.is_apple else 1
        if self.settings.reverse_scroll:
            multiplier = -multiplier
        self.wheel_x += event.angleDelta().x() * multiplier
        self.wheel_y += event.angleDelta().y() * multiplier
        steps = []
        for axis in ("wheel_x", "wheel_y"):
            delta = getattr(self, axis)
            direction = 1 if delta >= 0 else -1
            count, remainder = divmod(abs(delta), 120)
            steps.append(direction * count)
            setattr(self, axis, direction * remainder)
        self.session.scroll(*position, self.buttons, *steps)
        event.accept()

    def keyPressEvent(self, event):
        if self.active():
            keysym = keysym_for(event)
            if keysym is not None:
                identity = event.nativeScanCode() or event.key()
                # Use the original keysym for repeated and released keys, even if modifiers changed.
                keysym = self.pressed.setdefault(identity, keysym)
                self.session.key(keysym, True)
        event.accept()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            identity = event.nativeScanCode() or event.key()
            keysym = self.pressed.pop(identity, None)
            if keysym is not None and self.session:
                self.session.key(keysym, False)
        event.accept()

    def inputMethodEvent(self, event):
        if self.active():
            for character in event.commitString():
                code = ord(character)
                keysym = code if code <= 255 else 0x01000000 | code
                self.session.key(keysym, True)
                self.session.key(keysym, False)
        event.accept()

    def release_input(self):
        self.move_timer.stop()
        self.pending_move = None
        if self.session:
            for keysym in self.pressed.values():
                self.session.key(keysym, False)
            if self.buttons:
                self.session.pointer(*self.position, 0)
        self.pressed.clear()
        self.buttons = 0
        self.wheel_x = self.wheel_y = 0

    def focusOutEvent(self, event):
        self.release_input()
        super().focusOutEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or Settings()
        self.worker = None
        self.intentional = False
        self.closing = False
        self.connected_once = False
        self.last_error = ""
        self.start_status_message = ""
        self.was_maximized = False
        self.remote_size = None
        self.setWindowTitle("Native VNC")
        self.setFont(interface_font())
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._make_start()
        self.view = RemoteView(self.settings)
        self.view.retry.clicked.connect(self.start_connection)
        self.stack.addWidget(self.view)
        self.apply_language()
        self.fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.apply_theme)
        self.apply_theme()
        self.show_login_window()

    def apply_theme(self, scheme=None):
        app = QApplication.instance()
        scheme = app.styleHints().colorScheme() if scheme is None else scheme
        dark = scheme == Qt.ColorScheme.Dark
        if scheme == Qt.ColorScheme.Unknown:
            dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
        apply_appearance(self, dark)
        self.title.ensurePolished()
        self.settings_button.setFixedHeight(self.title.sizeHint().height())
        self.form.ensurePolished()
        self.form.setFixedHeight(self.form.layout().sizeHint().height())

    def _make_start(self):
        self.start = QWidget()
        self.start.setObjectName("start")
        # A hidden login form must not impose its minimum height on the remote desktop.
        self.start.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(self.start)
        layout.setContentsMargins(18, 20, 18, 10)
        layout.setSpacing(0)
        form = QWidget()
        self.form = form
        form.setFixedWidth(300)
        fields = QVBoxLayout(form)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(6)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(8)
        self.title = QLabel("Native VNC")
        self.title.setObjectName("appTitle")
        heading.addWidget(self.title)
        heading.addStretch()
        self.settings_button = QPushButton()
        self.settings_button.setObjectName("settings")
        self.settings_button.clicked.connect(self.show_settings)
        heading.addWidget(self.settings_button)
        fields.addLayout(heading)
        self.address_label = QLabel()
        fields.addWidget(self.address_label)
        self.address = QLineEdit(str(self.settings.values.get("address", "")))
        self.address.setClearButtonEnabled(True)
        fields.addWidget(self.address)
        self.username_label = QLabel()
        fields.addWidget(self.username_label)
        self.username = QLineEdit(str(self.settings.values.get("username", "")))
        fields.addWidget(self.username)
        self.password_label = QLabel()
        fields.addWidget(self.password_label)
        self.password = QLineEdit(self.settings.password())
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        fields.addWidget(self.password)
        self.credential_identity = (self.address.text(), self.username.text())
        self.address.textEdited.connect(self.identity_edited)
        self.username.textEdited.connect(self.identity_edited)
        self.remember = QCheckBox()
        self.remember.setMinimumHeight(24)
        self.remember.setChecked(self.settings.values.get("remember_password") is True)
        fields.addWidget(self.remember)
        fields.addSpacing(10)
        self.connect_button = QPushButton()
        self.connect_button.setObjectName("connect")
        self.connect_button.clicked.connect(self.connect_or_cancel)
        self._form_enabled(True)
        fields.addWidget(self.connect_button)
        self.start_status = QLabel()
        self.start_status.setObjectName("startStatus")
        self.start_status.setWordWrap(True)
        self.start_status.setFixedWidth(300)
        # Status is outside the form, so showing or wrapping it never moves fields.
        self.start_status.hide()
        layout.addWidget(form, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.start_status, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.stack.addWidget(self.start)
        self.address.returnPressed.connect(self.connect_or_cancel)
        self.username.returnPressed.connect(self.connect_or_cancel)
        self.password.returnPressed.connect(self.connect_or_cancel)
        self.address.setFocus()

    def localize(self, message):
        return translate(message, self.settings.language)

    def apply_language(self):
        for widget, label, source, placeholder in (
            (self.address, self.address_label, "服务器地址", "192.168.1.10:5900 或 wss://…"),
            (self.username, self.username_label, "用户名", "Mac 账户短名称；普通 VNC 留空"),
            (self.password, self.password_label, "密码", "Mac 登录密码，或 VNC 密码"),
        ):
            label.setText(self.localize(source))
            widget.setAccessibleName(label.text())
            widget.setPlaceholderText(self.localize(placeholder))
        self.settings_button.setText(self.localize("设置"))
        self.settings_button.setToolTip(self.settings_button.text())
        self.remember.setText(self.localize("记住密码"))
        self.view.retry.setText(self.localize("重新连接"))
        self._form_enabled(self.worker is None)
        self.form.setFixedHeight(self.form.layout().sizeHint().height())
        self.set_start_status(self.start_status_message)

    def show_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_language()
        dialog.deleteLater()

    def show_login_window(self):
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.setMinimumSize(340, 310)
        self.resize(360, 330)
        available = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        frame = self.frameGeometry()
        self.move(available.center().x() - frame.width() // 2,
                  available.center().y() - frame.height() // 2)

    def restore_desktop_window(self):
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        state = self.settings.values.get("desktop_window", {})
        if not isinstance(state, dict):
            state = {}
        geometry = state.get("geometry") if self.settings.remember_window_size else None
        if isinstance(geometry, list) and len(geometry) == 4 and all(isinstance(v, int) for v in geometry):
            x, y, width, height = geometry
            candidate = QRect(x, y, max(self.minimumWidth(), width), max(self.minimumHeight(), height))
            screen = next((screen for screen in QApplication.screens()
                           if screen.availableGeometry().contains(candidate.center())), QApplication.primaryScreen())
            available = screen.availableGeometry()
            frame_width = self.frameGeometry().width() - self.width()
            frame_height = self.frameGeometry().height() - self.height()
            left = self.geometry().left() - self.frameGeometry().left()
            top = self.geometry().top() - self.frameGeometry().top()
            width = min(candidate.width(), available.width() - frame_width)
            height = min(candidate.height(), available.height() - frame_height)
            x = max(available.left() + left,
                    min(x, available.right() - (frame_width - left) - width + 1))
            y = max(available.top() + top,
                    min(y, available.bottom() - (frame_height - top) - height + 1))
            self.setGeometry(x, y, width, height)
        else:
            self.resize(960, 640)
        self.was_maximized = state.get("maximized") is True
        if state.get("fullscreen") is True:
            self.showFullScreen()
        elif self.was_maximized:
            self.showMaximized()

    def remember_desktop_window(self):
        if self.stack.currentWidget() is not self.view or self.remote_size is None:
            return False
        fullscreen = self.isFullScreen()
        maximized = self.was_maximized if fullscreen else self.isMaximized()
        state = {
            "fullscreen": fullscreen,
            "maximized": maximized,
        }
        if self.settings.remember_window_size:
            geometry = self.normalGeometry() if fullscreen or maximized else self.geometry()
            state["geometry"] = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        self.settings.values["desktop_window"] = state
        return True

    def _form_enabled(self, enabled):
        for widget in (self.address, self.username, self.password, self.remember):
            widget.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.connect_button.setText(self.localize("连接" if enabled else "取消"))
        font = self.connect_button.font()
        font.setBold(enabled)
        self.connect_button.setFont(font)
        self.connect_button.setEnabled(True)

    def connect_or_cancel(self):
        if self.worker:
            self.disconnect_from_server()
        else:
            self.start_connection()

    def identity_edited(self):
        if (self.address.text().strip(), self.username.text().strip()) != self.credential_identity:
            self.password.clear()

    def start_connection(self):
        if self.worker or self.closing:
            return
        try:
            endpoint = Endpoint.parse(self.address.text())
        except ValueError as exc:
            self.stack.setCurrentWidget(self.start)
            self.set_start_status(str(exc))
            self.address.setFocus()
            return
        self.address.setText(self.address.text().strip())
        self.username.setText(self.username.text().strip())
        self.remember_desktop_window()
        try:
            self.settings.remember(self.address.text(), self.remember.isChecked(), self.username.text())
        except OSError:
            self.set_start_status("配置暂时无法保存，仍可连接。")
        self.intentional = False
        self.connected_once = False
        self.last_error = ""
        self._form_enabled(False)
        self.remote_size = None
        self.view.session = None
        self.view.unsetCursor()
        self.view.show_message(self.localize("正在连接服务器…"), retry=False)
        self.worker = NetworkWorker(endpoint, self.password.text(), self, username=self.username.text())
        self.worker.status.connect(self.on_status)
        self.worker.connected.connect(self.on_connected)
        self.worker.frame.connect(self.on_frame)
        self.worker.cursor.connect(self.view.set_remote_cursor)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_status(self, message):
        self.set_start_status(message)
        if self.view.message:
            self.view.message_label.setText(self.localize(message))

    def on_connected(self, name):
        if self.intentional or self.closing:
            return
        self.connected_once = True
        self.view.session = self.worker.session
        self.view.image = QImage()
        self.view._frame_pixels = b""
        self.view.clear_message()
        self.setMinimumSize(320, 180)
        self.stack.setCurrentWidget(self.view)
        self.restore_desktop_window()
        self.setWindowTitle(f"{self.localize(name[:100])} — Native VNC")
        self.view.setFocus()
        try:
            self.settings.authenticated(self.password.text())
            self.credential_identity = (self.address.text(), self.username.text())
        except OSError:
            pass

    def on_frame(self):
        if self.worker is None:
            return
        frame = self.worker.take_frame()
        if self.intentional or self.closing or frame is None:
            return
        width, height, pixels = frame
        self.view.set_frame(width, height, pixels)
        if self.remote_size != (width, height):
            self.remote_size = (width, height)
            QTimer.singleShot(0, self.fit_remote_window)

    def fit_remote_window(self):
        if (not self.remote_size or self.stack.currentWidget() is not self.view
                or self.isFullScreen() or self.isMaximized()):
            return
        width = self.width()
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        frame_width = self.frameGeometry().width() - self.width()
        frame_height = self.frameGeometry().height() - self.height()
        max_width = available.width() - frame_width
        max_height = available.height() - frame_height
        remote_width, remote_height = self.remote_size
        # Change the window, never the framebuffer or its aspect ratio.
        width = min(width, max_width)
        height = round(width * remote_height / remote_width)
        if height > max_height:
            height = max_height
            width = round(height * remote_width / remote_height)
        if height < self.minimumHeight():
            height = self.minimumHeight()
            width = round(height * remote_width / remote_height)
        self.resize(width, height)
        frame = self.frameGeometry()
        self.move(max(available.left(), min(frame.left(), available.right() - frame.width() + 1)),
                  max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1)))

    def set_start_status(self, message=""):
        self.start_status_message = message
        self.start_status.setText(self.localize(message))
        self.start_status.setFixedHeight(max(self.start_status.sizeHint().height(),
                                             self.start_status.heightForWidth(300)) if message else 0)
        self.start_status.setVisible(bool(message))
        if message and self.stack.currentWidget() is self.start:
            self.start.layout().activate()
            height = self.start.layout().minimumSize().height()
            self.resize(self.width(), max(self.height(), height))

    def on_failure(self, message):
        self.last_error = message

    def on_finished(self):
        worker = self.worker
        self.worker = None
        self.view.release_input()
        self.view.session = None
        self._form_enabled(True)
        if worker:
            worker.deleteLater()
        if self.closing:
            self.close()
        elif self.intentional:
            self.show_start()
        elif self.connected_once:
            self.view.show_message(self.localize(self.last_error or "连接已断开。"))
        else:
            self.stack.setCurrentWidget(self.start)
            self.set_start_status(self.last_error or "连接已取消。")
            self.password.setFocus()

    def disconnect_from_server(self):
        self.intentional = True
        self.view.release_input()
        if self.worker:
            self.worker.session.stop()
            self.on_status("正在断开…")
            self.connect_button.setEnabled(False)
        else:
            self.show_start()

    def show_start(self):
        if self.remember_desktop_window():
            try:
                self.settings.save()
            except OSError:
                pass
        self.stack.setCurrentWidget(self.start)
        self.show_login_window()
        self.remote_size = None
        self.view.image = QImage()
        self.view._frame_pixels = b""
        self.view.clear_message()
        self.setWindowTitle("Native VNC")
        self.set_start_status()
        self.connect_button.setFocus()

    def toggle_fullscreen(self):
        if self.stack.currentWidget() is not self.view:
            return
        self.view.release_input()
        if self.isFullScreen():
            if self.was_maximized:
                self._show_maximized_without_animation()
            else:
                # Preserve normal geometry before Qt asynchronously restores it.
                geometry = self.normalGeometry()
                self.showNormal()
                self.setGeometry(geometry)
                self.fit_remote_window()
        else:
            self.was_maximized = self.isMaximized()
            self.showFullScreen()
        self.view.setFocus()

    def _show_maximized_without_animation(self):
        if QApplication.platformName() != "windows":
            self.showMaximized()
            return

        import ctypes
        from ctypes import wintypes

        # Qt restores the normal rectangle before maximizing on Windows.
        # Suppress that intermediate animation for this window and transition only.
        dwm = ctypes.WinDLL("dwmapi")
        hwnd = wintypes.HWND(int(self.winId()))
        disabled = wintypes.BOOL(True)
        attribute = 3  # DWMWA_TRANSITIONS_FORCEDISABLED
        changed = dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(disabled),
                                            ctypes.sizeof(disabled)) == 0
        try:
            self.showMaximized()
            if changed:
                dwm.DwmFlush()
        finally:
            if changed:
                disabled.value = False
                dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(disabled),
                                         ctypes.sizeof(disabled))

    def application_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self.view.release_input()

    def shutdown(self):
        if self.worker is not None:
            self.view.release_input()
            self.worker.session.stop()
            self.worker.wait()

    def closeEvent(self, event):
        if not self.closing:
            self.remember_desktop_window()
            try:
                self.settings.remember(self.address.text().strip(), self.remember.isChecked(),
                                       self.username.text().strip())
            except OSError:
                pass
            self.closing = True
        if self.worker:
            self.disconnect_from_server()
            event.ignore()
            return
        event.accept()
