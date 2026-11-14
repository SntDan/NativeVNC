"""Exercise Qt wheel input through the real RFB queue without a server or display."""

import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog

from native_vnc.preferences import SettingsDialog
from native_vnc.protocol import Endpoint, Session
from native_vnc.settings import Settings
from native_vnc.window import RemoteView


class ScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory(prefix="nativevnc-scroll-test-")
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(Path(self.directory.name) / "settings.json")
        self.session = Session(Endpoint.parse("localhost:5900"))
        self.session.ready.set()
        self.session.is_apple = True
        self.view = RemoteView(self.settings)
        self.view.resize(200, 200)
        self.view.set_frame(200, 100, bytes(200 * 100 * 4))
        self.view.session = self.session
        self.addCleanup(self.view.close)

    def wheel(self, x=0, y=0, position=(100, 100)):
        event = QWheelEvent(QPointF(*position), QPointF(*position), QPoint(), QPoint(x, y),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        self.view.wheelEvent(event)

    def messages(self):
        batches = []
        while not self.session.outgoing.empty():
            batches.append(self.session.outgoing.get_nowait())
        return batches, [message for batch in batches
                         for message in struct.iter_unpack("!BBHH", batch)]

    def test_mac_notch_is_fifty_complete_clicks_in_one_batch(self):
        self.wheel(y=120)
        batches, messages = self.messages()
        self.assertEqual(len(batches), 1)
        self.assertEqual(messages, [(5, 8, 100, 50), (5, 0, 100, 50)] * 50)

    def test_all_four_directions_preserve_held_buttons(self):
        self.view.buttons = 5  # Left and right held during scrolling.
        for x, y, bit in ((0, 120, 8), (0, -120, 16), (120, 0, 32), (-120, 0, 64)):
            with self.subTest(x=x, y=y):
                self.wheel(x=x, y=y)
                _, messages = self.messages()
                self.assertEqual(messages, [(5, 5 | bit, 100, 50), (5, 5, 100, 50)] * 50)

    def test_standard_server_keeps_original_speed_and_multiple_notches(self):
        self.session.is_apple = False
        self.wheel(y=360)
        _, messages = self.messages()
        self.assertEqual(messages, [(5, 8, 100, 50), (5, 0, 100, 50)] * 3)

    def test_high_resolution_mac_deltas_accumulate_before_quantization(self):
        self.wheel(y=1)
        self.wheel(y=1)
        self.assertEqual(self.messages()[1], [])
        self.wheel(y=1)
        self.assertEqual(self.messages()[1], [(5, 8, 100, 50), (5, 0, 100, 50)])
        self.assertEqual(self.view.wheel_y, 30)
        for _ in range(3):
            self.wheel(y=-1)
        self.assertEqual(self.messages()[1], [(5, 16, 100, 50), (5, 0, 100, 50)])
        self.assertEqual(self.view.wheel_y, 0)

    def test_standard_fractional_deltas_cancel_on_direction_change(self):
        self.session.is_apple = False
        self.wheel(y=60)
        self.wheel(y=-60)
        self.assertEqual(self.messages()[1], [])
        self.wheel(y=-120)
        self.assertEqual(self.messages()[1], [(5, 16, 100, 50), (5, 0, 100, 50)])

    def test_diagonal_scroll_uses_independent_axes(self):
        self.wheel(x=-120, y=120)
        batches, messages = self.messages()
        self.assertEqual(len(batches), 1)
        self.assertEqual(messages, ([(5, 8, 100, 50), (5, 0, 100, 50)] * 50 +
                                    [(5, 64, 100, 50), (5, 0, 100, 50)] * 50))

    def test_excess_steps_are_capped_without_a_later_scroll_tail(self):
        self.wheel(y=120 * 1000)
        batches, messages = self.messages()
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(messages), 1000)  # 500 press/release pairs.
        self.assertEqual(self.view.wheel_y, 0)
        self.wheel(y=120)
        self.assertEqual(len(self.messages()[1]), 100)

    def test_pending_pointer_move_precedes_scroll_at_new_position(self):
        self.view.pending_move = (10, 20)
        self.wheel(y=120)
        batches, messages = self.messages()
        self.assertEqual(len(batches), 2)
        self.assertEqual(messages[0], (5, 0, 10, 20))
        self.assertEqual(messages[1], (5, 8, 100, 50))
        self.assertIsNone(self.view.pending_move)

    def test_letterbox_and_inactive_session_do_not_scroll(self):
        self.wheel(y=120, position=(100, 10))
        self.assertEqual(self.messages()[1], [])
        self.session.ready.clear()
        self.wheel(y=120)
        self.assertEqual(self.messages()[1], [])

    def test_focus_release_clears_fractional_remainders(self):
        self.wheel(x=1, y=-1)
        self.view.release_input()
        self.assertEqual((self.view.wheel_x, self.view.wheel_y), (0, 0))

    def test_saved_multiplier_applies_immediately_and_survives_reload(self):
        self.settings.set_preferences("en", True, 2, False)
        self.wheel(y=120)
        self.assertEqual(len(self.messages()[1]), 4)
        self.assertEqual(Settings(self.settings.path).mac_scroll_multiplier, 2)
        self.settings.set_preferences("en", True, 1, False)
        self.wheel(y=120)
        self.assertEqual(len(self.messages()[1]), 2)

    def test_invalid_saved_multiplier_falls_back_to_default(self):
        for value in (None, True, 0, 101, "50", 1.5):
            with self.subTest(value=value):
                self.settings.values["mac_scroll_multiplier"] = value
                self.assertEqual(self.settings.mac_scroll_multiplier, 50)

    def test_failed_settings_save_rolls_back_preferences(self):
        self.settings.set_preferences("en", True, 5, False)
        with patch.object(self.settings, "save", side_effect=OSError("test failure")):
            with self.assertRaises(OSError):
                self.settings.set_preferences("zh_CN", False, 25, True)
        self.assertEqual(self.settings.mac_scroll_multiplier, 5)
        self.assertEqual(self.settings.language, "en")
        self.assertTrue(self.settings.remember_window_size)
        self.assertFalse(self.settings.reverse_scroll)

    def test_reverse_scroll_is_disabled_by_default_and_rejects_non_booleans(self):
        self.assertFalse(self.settings.reverse_scroll)
        for value in (None, 1, "true", "false", False):
            with self.subTest(value=value):
                self.settings.values["reverse_scroll"] = value
                self.assertFalse(self.settings.reverse_scroll)

    def test_reverse_scroll_swaps_both_axes_for_mac_and_standard_servers(self):
        self.settings.values["reverse_scroll"] = True
        for apple in (False, True):
            self.session.is_apple = apple
            repeats = 50 if apple else 1
            for x, y, bit in ((0, 120, 16), (0, -120, 8), (120, 0, 64), (-120, 0, 32)):
                with self.subTest(apple=apple, x=x, y=y):
                    self.wheel(x=x, y=y)
                    self.assertEqual(self.messages()[1],
                                     [(5, bit, 100, 50), (5, 0, 100, 50)] * repeats)

    def test_cancel_does_not_change_saved_scroll_preferences(self):
        dialog = SettingsDialog(self.settings)
        self.addCleanup(dialog.close)
        dialog.reverse_scroll.setChecked(True)
        dialog.scroll_multiplier.setValue(2)
        dialog.reject()
        self.assertFalse(self.settings.reverse_scroll)
        self.assertEqual(self.settings.mac_scroll_multiplier, 50)
        self.assertFalse(self.settings.path.exists())

    def test_preferences_localize_and_save_multiplier(self):
        dialog = SettingsDialog(self.settings)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.scroll_multiplier.value(), 50)
        self.assertEqual(dialog.scroll_label.text(), "Mac scroll speed")
        self.assertFalse(dialog.reverse_scroll.isChecked())
        self.assertEqual(dialog.reverse_scroll.text(), "Reverse scroll direction")
        dialog.language.setCurrentIndex(dialog.language.findData("zh_CN"))
        self.assertEqual(dialog.scroll_label.text(), "Mac 滚轮速度")
        self.assertEqual(dialog.reverse_scroll.text(), "反转滚轮方向")
        dialog.scroll_multiplier.setValue(15)
        dialog.reverse_scroll.setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        reloaded = Settings(self.settings.path)
        self.assertEqual(reloaded.mac_scroll_multiplier, 15)
        self.assertEqual(reloaded.language, "zh_CN")
        self.assertTrue(reloaded.reverse_scroll)


if __name__ == "__main__":
    unittest.main()
