import os
from queue import Empty, SimpleQueue
import struct
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from canable_sdk import CANFrame
from cangui.i18n import _TR, get_language, set_language
from plugins.boot_upgrade import protocol
from plugins.boot_upgrade.upgrader import BootConfig, UpgradeSignals, UpgradeTask
from plugins.boot_upgrade.widget import BootUpgradePanel


class Context:
    def __init__(self):
        self.sent = []
        self.settings = {"boot_upgrade.host_id": 0x703}

    def is_connected(self):
        return True

    def send_frame(self, frame):
        self.sent.append(frame)

    def get_setting(self, key, default):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value


class BootUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_info_query_matches_node_and_token_and_displays_out_of_order_pages(self):
        from plugins.boot_upgrade.widget import _I18N_KEYS

        previous_language = get_language()
        self.addCleanup(set_language, previous_language)
        set_language("en")
        context = Context()
        translations = {k: {"zh": zh, "en": en} for k, (zh, en) in _I18N_KEYS.items()}
        with patch.dict(_TR, translations):
            panel = BootUpgradePanel(context)
            self.addCleanup(panel.deleteLater)
            panel._interval_spin.setValue(20)
            self.assertEqual(context.settings["boot_upgrade.frame_interval_ms"], 20)
            panel._interval_spin.setValue(0)
            self.assertEqual(context.settings["boot_upgrade.frame_interval_ms"], 0)
            panel._load_config_to_ui()
            self.assertEqual(panel._interval_spin.value(), 0)
            panel._query_btn.click()
            request = context.sent.pop()
            self.assertEqual(request.can_id, 0x703)
            self.assertEqual(request.data[0], protocol.Cmd.GET_INFO)
            self.assertFalse(panel._query_btn.isEnabled())

            token = request.data[1]
            payload = struct.pack(">IIIIIHBBB", 0x010203, 8, 12, 20000, 0x1234, 1, 1, 1, 0)
            pages = [CANFrame(0x704, bytes([protocol.Cmd.INFO, token, i]) + payload[i*5:i*5+5])
                     for i in range(protocol.INFO_PAGE_COUNT)]
            panel.on_frames([CANFrame(0x705, pages[0].data),
                             CANFrame(0x704, bytes([protocol.Cmd.INFO, token + 1, 0]) + bytes(5)),
                             *reversed(pages[1:])])
            self.assertFalse(panel._query_btn.isEnabled())
            panel.on_frames([pages[0]])
            self.assertIn("Firmware V1.2.3", panel._info_label.text())
            self.assertIn("Boots 8", panel._info_label.text())
            self.assertIn("Successful", panel._info_label.text())
            self.assertTrue(panel._query_btn.isEnabled())

    def test_pacing_applies_even_if_receive_returns_immediately(self):
        class Clock:
            now = 0.0

            def perf_counter(self):
                return self.now

            def sleep(self, duration):
                self.now += duration

        class Bus:
            def __init__(self):
                self.timestamps = []

            def send(self, frame):
                self.timestamps.append(clock.perf_counter())

        clock = Clock()
        for interval_ms, expected in ((0, [0.0, 0.0, 0.0]), (20, [0.0, 0.02, 0.04])):
            with self.subTest(interval_ms=interval_ms):
                clock.now = 0.0
                task = UpgradeTask(BootConfig(fw=b"", host_id=0x703, frame_interval_ms=interval_ms),
                                   UpgradeSignals())
                task._bus = Bus()
                with patch("plugins.boot_upgrade.upgrader.time", clock):
                    task._send(b"\x03", 8)
                    task._responses.put(CANFrame(0x704, b"\x11\x03\x05\x00\x00"))
                    self.assertIsNotNone(task._poll_response())
                    task._send(b"\x08", 8)
                    task._send(b"\x04", 8)
                self.assertEqual(task._bus.timestamps, expected)

    def test_usb_read_timeout_does_not_set_data_frame_spacing(self):
        class SlowUsbBus:
            def __init__(self):
                self.responses = SimpleQueue()

            def send(self, frame):
                cmd = frame.data[0]
                if cmd != protocol.Cmd.DATA:
                    self.responses.put(CANFrame(0x704, bytes([protocol.Cmd.ACK, cmd]) + bytes(6)))

            def receive(self, timeout):
                try:
                    # The adapter can take at least 15 ms to return an empty read.
                    return self.responses.get(timeout=max(timeout, 0.015))
                except Empty:
                    return None

        timing = []
        for interval_ms in (0, 1, 15):
            result = []
            signals = UpgradeSignals()
            signals.finished.connect(lambda ok, msg: result.append((ok, msg)))
            signals.timing.connect(lambda avg, minimum, count: timing.append((avg, minimum, count)))
            UpgradeTask(BootConfig(fw=bytes(1024), host_id=0x703, frame_interval_ms=interval_ms),
                        signals).run(SlowUsbBus())
            self.assertTrue(result[0][0], result[0][1])
        (zero, _, zero_count), (fast, fast_min, fast_count), (slow, slow_min, slow_count) = timing
        self.assertEqual((zero_count, fast_count, slow_count), (16, 16, 16))
        self.assertLess(zero, fast)
        self.assertGreaterEqual(fast_min, 0.99)
        self.assertGreaterEqual(slow_min, 14.99)
        self.assertLess(fast, slow / 2)


if __name__ == "__main__":
    unittest.main()
