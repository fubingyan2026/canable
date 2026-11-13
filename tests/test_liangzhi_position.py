"""Offline checks for per-axis motion commands and slider cancellation."""
import math
import os
import struct
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from canable_sdk import CANFrame
from cangui.plugin_host import PluginContext
from plugins.liangzhi_position.plugin import create_plugin
from plugins.liangzhi_position.widget import tr


class PositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ctx = PluginContext(None)
        self.plugin = create_plugin()
        self.plugin.init(self.ctx)
        self.send = self.enterContext(patch.object(self.ctx, "send_frame"))
        self.connected = self.enterContext(patch.object(self.ctx, "is_connected", return_value=True))
        self.fd_mode = self.enterContext(patch.object(self.ctx, "is_fd_mode", return_value=True))
        self.settings = {}
        self.enterContext(patch.object(self.ctx, "get_setting", side_effect=self.settings.get))
        self.enterContext(patch.object(self.ctx, "set_setting", side_effect=self.settings.__setitem__))
        self.panel = self.plugin.build_widget(self.ctx)
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.reset_feedback)

    @staticmethod
    def click(axis, key):
        next(button for button in axis.findChildren(QPushButton) if button.text() == tr(key)).click()

    def sent(self):
        return [call.args[0] for call in self.send.call_args_list]

    def test_position_mode_axis_states_and_feedforward_use_each_node(self):
        first, second = self.panel.axes.values()
        self.send.assert_not_called()
        self.click(first, "SetMode")
        self.click(second, "ClosedLoop")
        self.click(first, "Idle")
        self.click(second, "Clear")
        second.trajectory_speed.setValue(3.5)
        self.click(second, "SetSpeed")
        self.panel.transport.setCurrentIndex(2)
        second.target.setValue(1.25)
        second.velocity.setValue(-0.5)
        second.torque.setValue(0.125)
        self.click(second, "SendTarget")
        frames = self.sent()
        self.assertEqual([f.can_id for f in frames], [0x02B, 0x047, 0x027, 0x058, 0x051, 0x04C])
        self.assertEqual(frames[0].data, struct.pack("<II", 3, 3))
        self.assertEqual(frames[1].data, struct.pack("<II", 8, 0))
        self.assertEqual(frames[2].data, struct.pack("<II", 1, 0))
        self.assertEqual(frames[3].data, bytes(8))
        factor = 35 / math.tau
        self.assertEqual(frames[4].data, struct.pack("<fI", 3.5 * factor, 0))
        self.assertEqual(frames[5].data, struct.pack("<fhh", 1.25 * factor, round(-500 * factor), 125))
        self.assertTrue(frames[5].fd and frames[5].brs)

    def test_jog_uses_its_own_feedback_and_slider_flushes_latest_target(self):
        first, second = self.panel.axes.values()
        self.click(first, "JogPlus")
        self.send.assert_not_called()
        self.panel.on_frames([CANFrame(0x029, struct.pack("<ff", 0.25, 0)),
                              CANFrame(0x049, struct.pack("<ff", 0.75, 0)),
                              CANFrame(0x029, struct.pack("<ff", 100, 0), is_tx=True)])
        first.jog_step.setValue(0.125)
        self.click(first, "JogPlus")
        factor = 35 / math.tau
        target = round(0.25 / factor + 0.125, 3)
        self.assertEqual(self.sent()[-1].data, struct.pack("<fhh", target * factor, 0, 0))
        self.assertIn(f"{0.25 / factor:.4f} rad", first.feedback.text())
        second.slider_min.setValue(-1)
        second.slider_max.setValue(1)
        second.slider.setSliderDown(True)
        second.slider.setValue(600)
        second.slider.setValue(750)
        self.assertEqual(self.send.call_count, 1)
        second.slider.setSliderDown(False)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.sent()[-1].can_id, 0x04C)
        self.assertEqual(self.sent()[-1].data, struct.pack("<fhh", 0.5 * factor, 0, 0))

        second.slider.setSliderDown(True)
        second.slider.setValue(800)
        self.click(second, "Idle")
        second.slider.setSliderDown(False)
        self.assertEqual(self.send.call_count, 3)
        self.assertEqual(self.sent()[-1].can_id, 0x047)

    def test_disconnect_and_fd_configuration_prevent_motion(self):
        axis = self.panel.axes[1]
        axis.slider.setSliderDown(True)
        axis.slider.setValue(650)
        self.connected.return_value = False
        self.panel.reset_feedback()
        axis.slider.setSliderDown(False)
        self.click(axis, "SendTarget")
        self.connected.return_value = True
        self.panel.transport.setCurrentIndex(2)
        self.fd_mode.return_value = False
        self.click(axis, "SendTarget")
        self.send.assert_not_called()

    def test_settings_reload_independent_axes_without_sending(self):
        first, second = self.panel.axes.values()
        self.assertEqual([axis.gear_ratio.value() for axis in (first, second)], [35, 35])
        first.gear_ratio.setValue(40)
        first.target.setValue(0.125)
        second.target.setValue(-0.5)
        second.mode.setCurrentIndex(second.mode.findData(5))
        second.slider_min.setValue(-2)
        second._select_firmware("endpoint_4.2.55.json")
        self.panel.transport.setCurrentIndex(2)
        self.panel.save_button.click()
        restored = self.plugin.build_widget(self.ctx)
        self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.transport.currentData(), 2)
        self.assertEqual(restored.axes[1].gear_ratio.value(), 40)
        self.assertEqual(restored.axes[2].gear_ratio.value(), 35)
        self.assertEqual(restored.axes[1].target.value(), 0.125)
        self.assertEqual(restored.axes[2].target.value(), -0.5)
        self.assertEqual(restored.axes[2].mode.currentData(), 5)
        self.assertEqual(restored.axes[2].slider_min.value(), -2)
        self.assertEqual(restored.axes[2].firmware.currentData(), "endpoint_4.2.55.json")
        self.send.assert_not_called()

    def test_zero_and_save_drive_address_the_selected_axis(self):
        first, second = self.panel.axes.values()
        self.click(first, "Zero")
        self.send.assert_not_called()
        second._select_firmware("endpoint_4.2.55.json")
        self.click(second, "Zero")
        self.click(first, "SaveDrive")
        self.click(second, "SaveDrive")
        self.assertEqual([f.can_id for f in self.sent()], [0x044, 0x03F, 0x05F])
        self.assertEqual(self.sent()[0].data, bytes.fromhex("00 0B 02 00 00 00 00 00"))
        self.assertEqual(self.sent()[1].data, bytes(8))
        self.assertEqual(self.sent()[2].data, bytes(8))

    def test_out_of_range_angular_feedforward_does_not_send(self):
        axis = self.panel.axes[1]
        axis.velocity.setValue(6)
        self.click(axis, "SendTarget")
        self.send.assert_not_called()
        self.assertEqual(axis._status[0], "InvalidVelocity")
