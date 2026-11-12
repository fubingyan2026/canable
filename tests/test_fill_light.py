"""Protocol vectors and offline Qt behavior for the fill-light plugin."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import struct
import unittest
from dataclasses import replace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from canable_sdk import CANFrame
from cangui import i18n
from plugins.fill_light import protocol as P
from plugins.fill_light.plugin import create_plugin


def heartbeat(level=500, motor=2, uptime=10000):
    return CANFrame(can_id=0x221, data=struct.pack('<BBHI', 1, motor, level, uptime), fd=True)


class ProtocolTests(unittest.TestCase):
    def test_document_control_vectors(self):
        for level, payload in ((0, '01 01 00 00 00 00 00 00'),
                               (250, '01 01 FA 00 00 00 00 00'),
                               (500, '01 01 F4 01 00 00 00 00'),
                               (1000, '01 01 E8 03 00 00 00 00')):
            frame = P.build_light_control(level)
            self.assertEqual(frame.data, bytes.fromhex(payload))
            self.assertEqual(frame.can_id, 0x220)
            self.assertEqual(frame.dlc, 8)
            self.assertTrue(frame.fd)
            self.assertFalse(frame.brs or frame.extended or frame.rtr)

    def test_out_of_range_is_rejected_without_clamping(self):
        for level in (-1, 1001, 65535, 1.5, True, '500'):
            with self.subTest(level=level), self.assertRaises(ValueError):
                P.build_light_control(level)

    def test_heartbeat_and_uint32_wrap_values(self):
        self.assertEqual(P.parse_status(heartbeat()), P.BoardStatus(2, 500, 10000))
        for state in range(5):
            for uptime in (0, 0xFFFFFFFF):
                self.assertEqual(P.parse_status(heartbeat(1000, state, uptime)),
                                 P.BoardStatus(state, 1000, uptime))

    def test_bad_status_flags_and_payloads_are_ignored(self):
        frame = heartbeat()
        invalid = [replace(frame, **flags) for flags in (
            {'can_id': 0x220}, {'extended': True}, {'fd': False}, {'brs': True},
            {'rtr': True}, {'is_tx': True}, {'_error_info': 'bus error'})]
        invalid += [replace(frame, data=data) for data in (
            b'', bytes(7), bytes(9), b'\x02' + frame.data[1:],
            struct.pack('<BBHI', 1, 5, 500, 0), struct.pack('<BBHI', 1, 2, 1001, 0))]
        for bad in invalid:
            with self.subTest(frame=bad):
                self.assertIsNone(P.parse_status(bad))


class FakeContext:
    def __init__(self):
        self.frames, self.messages, self.settings = [], [], {}
        self.connected, self.fd, self.bitrate = True, True, 1_000_000

    def register_i18n(self, key, zh, en):
        i18n._TR[key] = {'zh': zh, 'en': en}

    def get_setting(self, key, default=None): return self.settings.get(key, default)
    def set_setting(self, key, value): self.settings[key] = value
    def send_frame(self, frame): self.frames.append(frame)
    def is_connected(self): return self.connected
    def is_fd_mode(self): return self.fd
    def get_bitrate(self): return self.bitrate
    def status_message(self, *args): self.messages.append(args)


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ctx = FakeContext()
        self.plugin = create_plugin()
        self.plugin.init(self.ctx)
        self.panel = self.plugin.build_widget(self.ctx)
        self.plugin.on_activated()
        self.plugin.on_connect()

    def tearDown(self):
        self.plugin.on_deactivating()
        self.plugin.teardown_widget(self.panel)
        i18n.set_language('zh')

    def test_creation_reconnect_and_language_change_do_not_send(self):
        self.panel._percent.setValue(42.3)
        self.assertEqual(self.panel._slider.value(), 423)
        for lang in ('en', 'zh'):
            i18n.set_language(lang)
            self.plugin.refresh_language()
            self.assertFalse(self.panel._apply_btn.text().startswith('FillLight.'))
        self.plugin.on_disconnect()
        self.plugin.on_connect()
        self.assertEqual(self.ctx.frames, [])
        self.assertEqual(self.panel._slider.value(), 423)
        self.assertEqual(self.ctx.settings['fill_light.level'], 423)

    def test_presets_off_and_restore_last_nonzero(self):
        button = self.panel._presets[0][0]
        button.click()
        self.assertEqual(self.ctx.frames[-1].data, P.build_light_control(250).data)
        self.panel._off.click()
        self.assertEqual(self.ctx.frames[-1].data, P.build_light_control(0).data)
        self.panel._on.click()
        self.assertEqual(self.ctx.frames[-1].data, P.build_light_control(250).data)
        self.assertEqual(len(self.ctx.frames), 3)

    def test_auto_debounce_and_immediate_off_cancel_pending_send(self):
        self.panel._auto.setChecked(True)
        self.panel._slider.setValue(100)
        self.panel._slider.setValue(600)
        self.assertFalse(self.ctx.frames)
        QTest.qWait(200)
        self.assertEqual(len(self.ctx.frames), 1)
        self.assertEqual(self.ctx.frames[-1].data, P.build_light_control(600).data)
        self.panel._slider.setValue(800)
        self.panel._off.click()
        QTest.qWait(200)
        self.assertEqual(len(self.ctx.frames), 2)
        self.assertEqual(self.ctx.frames[-1].data, P.build_light_control(0).data)

    def test_invalid_bus_configuration_never_sends(self):
        for config in ({'connected': False}, {'fd': False}, {'bitrate': 500000}):
            with self.subTest(config=config):
                old = {key: getattr(self.ctx, key) for key in config}
                for key, value in config.items(): setattr(self.ctx, key, value)
                self.panel._apply()
                self.assertFalse(self.ctx.frames)
                for key, value in old.items(): setattr(self.ctx, key, value)

    def test_heartbeat_freshness_matching_and_timeout(self):
        with patch('plugins.fill_light.widget.time.monotonic', return_value=10):
            self.plugin.on_frames([heartbeat()])
            self.panel._apply_btn.click()
            self.assertIsNotNone(self.panel._pending_level)  # Old snapshot is not a reply.
            self.plugin.on_frames([heartbeat(250)])
            self.assertEqual(self.panel._message_key, 'FillLight.Mismatch')
            self.plugin.on_frames([heartbeat(500)])
            self.assertEqual(self.panel._message_key, 'FillLight.Matched')
        with patch('plugins.fill_light.widget.time.monotonic', return_value=11.5):
            self.panel._refresh_status()
            self.assertEqual(self.panel._accepted.text(), i18n._('FillLight.NoData'))
            self.assertEqual(self.panel._connection.text(), i18n._('FillLight.Offline'))
        with patch('plugins.fill_light.widget.time.monotonic', return_value=12):
            self.panel._apply()
        with patch('plugins.fill_light.widget.time.monotonic', return_value=13.5):
            self.panel._refresh_status()
            self.assertEqual(self.panel._message_key, 'FillLight.Timeout')
            self.assertIsNone(self.panel._pending_level)
            self.plugin.on_frames([heartbeat(500, 4, 0)])
            self.assertEqual(self.panel._motor.text(), i18n._('FillLight.Motor.4'))
            self.assertEqual(self.panel._accepted.text(), '50.0%')

    def test_invalid_frames_do_not_refresh_online_time(self):
        self.plugin.on_frames([replace(heartbeat(), is_tx=True), heartbeat(1001)])
        self.assertIsNone(self.panel._last_rx)
        self.assertEqual(self.panel._connection.text(), i18n._('FillLight.Unknown'))

    def test_deactivation_disconnect_stop_deferred_commands(self):
        self.panel._auto.setChecked(True)
        self.panel._slider.setValue(700)
        self.ctx.connected = False
        self.plugin.on_disconnect()
        QTest.qWait(200)
        self.assertFalse(self.ctx.frames)
        self.ctx.connected = True
        self.plugin.on_connect()
        self.panel._slider.setValue(800)
        self.plugin.on_deactivating()
        QTest.qWait(200)
        self.assertFalse(self.ctx.frames)
        self.assertFalse(self.panel._poll.isActive())


if __name__ == '__main__':
    unittest.main()
