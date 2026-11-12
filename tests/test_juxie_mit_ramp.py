"""MIT 位置读取与斜坡的 CAN 帧验证（无需电机或适配器）。"""
import os
import struct
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from canable_sdk import CANFrame
from plugins.juxie_motor import protocol as P
from plugins.juxie_motor.widget import JuxieMotorPanel


class MotorContext:
    def __init__(self):
        self.connected = True
        self.frames = []
        self.statuses = []
        self.settings = {"juxie_motor.auto_request": False,
                         "juxie_motor.auto_send": False}

    def get_setting(self, key, default):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def is_connected(self):
        return self.connected

    def is_fd_mode(self):
        return True

    def send_frame(self, frame):
        self.frames.append(frame)

    def status_message(self, message, duration=0):
        self.statuses.append(message)


def feedback(dev_id, position_raw, **kwargs):
    kwargs.setdefault("timestamp", time.time())
    data = struct.pack(">h", position_raw) + bytes(10)
    return CANFrame(can_id=P.build_feedback_canid(dev_id), data=data, fd=True, **kwargs)


class MitRampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ctx = MotorContext()
        self.panel = JuxieMotorPanel(self.ctx)
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.on_deactivating)
        self.panel._pos_slider.setValue(100)

    def assert_positions(self, *expected):
        frames = self.ctx.frames[-len(expected):]
        for dev_id, frame, angle in zip((1, 2), frames, expected):
            self.assertEqual(frame.can_id, P.build_mit_single_canid(dev_id))
            raw = int.from_bytes(frame.data[1:3], "big")
            degrees = (raw / 65535.0 * 2.0 - 1.0) * 180.0
            self.assertAlmostEqual(degrees, angle, delta=0.003)

    def test_mirror_waits_for_both_and_ramps_from_independent_positions(self):
        stale_mirror = feedback(2, -1000, timestamp=time.time() - 0.1)
        self.panel._send_btn.click()
        self.panel.on_frames([stale_mirror, feedback(1, -1000),
                              feedback(2, 1000, extended=True)])
        self.assertEqual([f.can_id for f in self.ctx.frames], [P.SYNC_ID])
        self.panel.on_frames([feedback(2, 2000)])
        primary = -1000 * 180 / 32767
        mirror = 2000 * 180 / 32767
        self.assert_positions(primary, mirror)
        self.panel._on_mit_tick()
        self.assert_positions(primary + 1.2, mirror - 1.2)

    def test_manual_send_stops_at_the_submitted_target(self):
        self.panel._mirror_chk.setChecked(False)
        self.panel._send_btn.click()
        self.panel.on_frames([feedback(1, 0)])
        self.assert_positions(0.0)
        self.panel._pos_slider.setValue(200)
        for _ in range(9):
            self.panel._on_mit_tick()
        self.assert_positions(10.0)
        self.assertFalse(self.panel._mit_timer.isActive())

    def test_auto_send_retargets_without_restarting_the_ramp(self):
        self.panel._mirror_chk.setChecked(False)
        self.panel._auto_send_chk.setChecked(True)
        self.panel._pos_slider.setValue(200)
        self.panel._pos_slider.setValue(100)
        self.assertEqual([f.can_id for f in self.ctx.frames], [P.SYNC_ID])
        self.panel.on_frames([feedback(1, 0)])
        self.panel._on_mit_tick()
        self.assert_positions(1.2)
        self.panel._pos_slider.setValue(-100)
        self.panel._on_mit_tick()
        self.assert_positions(0.0)

    def test_continuous_uses_fresh_feedback_and_keeps_sending(self):
        self.panel._mirror_chk.setChecked(False)
        self.panel.on_frames([feedback(1, 1000, timestamp=time.time() - 0.1)])
        self.panel._pos_slider.setValue(5)
        self.panel._mit_cont_chk.setChecked(True)
        self.assertEqual([f.can_id for f in self.ctx.frames], [P.SYNC_ID])
        self.panel.on_frames([feedback(1, 0)])
        self.assert_positions(0.0)
        self.panel._on_mit_tick()
        self.assert_positions(0.5)
        self.assertTrue(self.panel._mit_timer.isActive())
        self.panel._mit_cont_chk.setChecked(False)
        self.assertFalse(self.panel._mit_timer.isActive())

    def test_timeout_and_mode_change_cancel_waiting(self):
        self.panel._send_btn.click()
        self.panel.on_frames([feedback(1, 0)])
        self.panel._on_mit_read_timeout()
        self.panel.on_frames([feedback(2, 0)])
        self.assertEqual([f.can_id for f in self.ctx.frames], [P.SYNC_ID])
        self.assertFalse(self.panel._mit_timer.isActive())
        self.panel._send_btn.click()
        self.panel._single_send.click()
        self.panel.on_frames([feedback(1, 0), feedback(2, 0)])
        self.assertEqual([f.can_id for f in self.ctx.frames],
                         [P.SYNC_ID, P.SYNC_ID, P.SINGLE_CONTROL_BASE | 1])

    def test_unrepresentable_feedback_does_not_start_ramp(self):
        self.panel._mirror_chk.setChecked(False)
        self.panel._pos_max_spin.setValue(90.0)
        self.panel._send_btn.click()
        self.panel.on_frames([feedback(1, -32768)])
        self.assertEqual([f.can_id for f in self.ctx.frames], [P.SYNC_ID])
        self.assertFalse(self.panel._mit_timer.isActive())
        self.assertFalse(self.panel._mit_read_timer.isActive())

    def test_disconnect_cancels_waiting_and_reconnect_reads_again(self):
        self.panel._mirror_chk.setChecked(False)
        self.panel._mit_cont_chk.setChecked(True)
        self.ctx.connected = False
        self.panel.on_disconnect()
        self.assertFalse(self.panel._mit_read_timer.isActive())
        self.ctx.connected = True
        self.panel.on_connect()
        self.panel.on_frames([feedback(1, -32768)])
        self.assertEqual([f.can_id for f in self.ctx.frames[:2]], [P.SYNC_ID, P.SYNC_ID])
        self.assert_positions(-180.0)
