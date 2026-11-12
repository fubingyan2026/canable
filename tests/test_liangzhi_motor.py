"""Regression vectors for Liangzhi MIT and 32-bit parameter readback."""
import os
import struct
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from canable_sdk import CANFrame
from cangui.i18n import get_language, set_language
from cangui.plugin_host import PluginContext
from plugins.liangzhi_motor import protocol as p
from plugins.liangzhi_motor.plugin import create_plugin


class LiangzhiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mit_feedback_uses_node_byte_and_configured_ranges(self):
        limits = p.MitLimits(position=20, velocity=40, torque=10)
        self.assertEqual(p.mit_payload((20, -40, 500, 0, 10), limits),
                         bytes.fromhex("FF FF 00 0F FF 00 0F FF"))
        feedback = bytes.fromhex("03 FF FF 00 0F FF 01 F6")
        self.assertEqual(p.mit_feedback(feedback, 3, limits), (20, -40, 10, 1, -10))
        self.assertIsNone(p.mit_feedback(feedback, 4, limits))

    def test_baud_readback_keeps_exact_value_and_ignores_other_nodes(self):
        ctx = PluginContext(None)
        plugin = create_plugin()
        plugin.init(ctx)
        with patch.object(ctx, "get_setting", side_effect=lambda _key, default: default), \
             patch.object(ctx, "is_connected", return_value=True), \
             patch.object(ctx, "send_frame") as send:
            panel = plugin.build_widget(ctx)
            try:
                param = p.Parameter("can.config.baud_rate", 69, "rw", "I")
                panel._parameter(param, None, False)
                sent = send.call_args.args[0]
                self.assertEqual(sent.can_id, 0x024)
                self.assertEqual(sent.data, bytes.fromhex("00 45 00 00 00 00 00 00"))
                response = bytes.fromhex("00 45 00 00 40 42 0F 00")
                panel.on_frames([CANFrame(0x045, response), CANFrame(0x025, response, is_tx=True)])
                self.assertIsNotNone(panel._request)
                panel.on_frames([CANFrame(0x025, response)])
                self.assertEqual(panel.status.text(), "can.config.baud_rate = 1000000")
            finally:
                panel.on_disconnect()
                plugin.teardown_widget(panel)

    def test_fault_feedback_keeps_axis_and_detail_code_spaces_separate(self):
        ctx = PluginContext(None)
        plugin = create_plugin()
        plugin.init(ctx)
        previous_language = get_language()
        set_language("zh")
        with patch.object(ctx, "get_setting", side_effect=lambda _key, default: default), \
             patch.object(ctx, "is_connected", return_value=True), \
             patch.object(ctx, "send_frame") as send:
            panel = plugin.build_widget(ctx)

            def displayed(key):
                row = list(panel._feedback).index(key)
                return panel.table.item(row, 1).text()

            try:
                heartbeat = struct.pack("<IBBbB", 0x80000840, 1, 0x81, 25, 1)
                panel.on_frames([CANFrame(0x021, heartbeat)])
                self.assertIn("0x80000840", displayed("AxisFault"))
                self.assertIn("MOTOR_FAILED", displayed("AxisFault"))
                self.assertIn("电机子系统报告故障", displayed("AxisFault"))
                self.assertIn("WATCHDOG_TIMER_EXPIRED", displayed("AxisFault"))
                self.assertIn("手册未列出的故障位 0x80000000", displayed("AxisFault"))
                self.assertIn("Motor_Flag", displayed("HeartbeatFaultFlags"))
                self.assertNotIn("0x80", displayed("HeartbeatFaultFlags"))
                send.assert_not_called()

                panel._send_simple(3, ("4",))
                panel.on_frames([CANFrame(0x023, struct.pack("<I", 0x40))])
                self.assertIn("BRAKE_DUTY_CYCLE_NAN", displayed("ErrorDetail"))
                self.assertNotIn("MOTOR_FAILED", displayed("ErrorDetail"))

                panel._send_simple(3, ("0",))
                panel.on_frames([CANFrame(0x023, struct.pack("<Q", 0x800000400))])
                self.assertIn("0x0000000800000400", displayed("ErrorDetail"))
                self.assertIn("CURRENT_SENSE_SATURATION", displayed("ErrorDetail"))
                self.assertIn("UNBALANCED_PHASES", displayed("ErrorDetail"))

                set_language("en")
                panel.refresh_language()
                self.assertIn("The motor subsystem reported a fault", displayed("AxisFault"))
                panel.on_frames([CANFrame(0x021, struct.pack("<IBBbB", 0, 1, 0, 25, 2))])
                self.assertIn("No fault", displayed("AxisFault"))
            finally:
                panel.on_disconnect()
                plugin.teardown_widget(panel)
                set_language(previous_language)
