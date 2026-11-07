"""Themes and compact plugin navigation preserve data without CAN commands."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import (QApplication, QLabel, QProgressBar,
                                  QPushButton, QScrollArea, QWidget)
    from PySide6.QtTest import QSignalSpy
except ImportError:
    QApplication = None

if QApplication is not None:
    from canable_sdk import CANFrame
    from cangui import style
    from cangui.__main__ import _pick_app_font
    from cangui.main_window import MainWindow
    from cangui.i18n import _
    from cangui.plugin_ui import DisclosureSection, FlowLayout
    from cangui.send import SendPanel
    from plugins.battery_monitor.protocol import VoltageData
    from plugins.keli_torque.scope import ValueScope
    from plugins.torque_sensor.scope import TorqueScope


@unittest.skipIf(QApplication is None, "PySide6 GUI extra is not installed")
class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setFont(_pick_app_font())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Path(self.temp.name) / "settings.json"
        self.settings.write_text(json.dumps({"theme": "light", "language": "zh"}))
        real_single_shot = QTimer.singleShot
        self.patches = [
            patch.object(MainWindow, "_settings_path", return_value=str(self.settings)),
            patch.object(SendPanel, "csv_path", return_value=str(Path(self.temp.name) / "send.csv")),
            patch("cangui.main_window.ZDTCanable.list_devices", return_value=[]),
            # Run layout callbacks; suppress delayed USB scanning in this suite.
            patch("cangui.main_window.QTimer.singleShot",
                  side_effect=lambda delay, callback: real_single_shot(0, callback) if delay == 0 else None),
        ]
        for item in self.patches:
            item.start()
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        style.apply_style(self.app, "light")
        self.temp.cleanup()

    def switch(self, theme):
        action = self.window.act_theme_dark if theme == "dark" else self.window.act_theme_light
        action.trigger()
        self.app.processEvents()

    def activate(self, name):
        plugin = next(plugin for plugin in self.window.plugins._plugins if plugin.name == name)
        plugin.activate()
        self.assertIsNotNone(plugin._widget)
        self.app.processEvents()
        return plugin._widget

    def test_menu_switch_updates_palette_and_is_exclusive(self):
        for theme in ("dark", "light", "dark"):
            self.switch(theme)
            self.assertEqual(style.current_theme(), theme)
            self.assertEqual(self.window.act_theme_dark.isChecked(), theme == "dark")
            self.assertEqual(self.window.act_theme_light.isChecked(), theme == "light")
            self.assertEqual(self.app.palette().color(QPalette.Base), QColor(style.BG_CARD))
            self.assertEqual(self.app.palette().color(QPalette.Mid), QColor(style.BORDER))
            self.assertEqual(self.window._get("theme"), theme)

    def test_theme_survives_restart(self):
        self.switch("dark")
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(json.loads(self.settings.read_text())["theme"], "dark")
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()
        self.assertEqual(style.current_theme(), "dark")
        self.assertTrue(self.window.act_theme_dark.isChecked())
        self.assertEqual(self.window.trace_panel.view._model._brush_tx.color(), QColor(style.BG_TX))

    def test_switch_preserves_frames_selection_settings_and_send_entries(self):
        frames = [CANFrame(0x123, b"12345678", timestamp=1),
                  CANFrame(0x321, b"abcdefgh", timestamp=2, is_tx=True)]
        self.window.trace_panel.append_frames(frames)
        view = self.window.trace_panel.view
        model = view._model
        view.selectRow(1)
        rows = model._rows
        before_id_color = model.data(model.index(0, model.COL_ID), Qt.ForegroundRole).color()
        self.window.fd_chk.setChecked(True)
        self.window.trace_panel.pause_btn.setChecked(True)
        self.window.send_panel.from_dict_list([dict(can_id=1, data="010203", period_ms=123)])
        entry = self.window.send_panel.entries[0]
        send_spy = QSignalSpy(self.window.send_panel.request_send)
        with patch.object(self.window.plugins._ctx, "send_frame") as send:
            self.switch("dark")
            send.assert_not_called()
        self.assertIs(model._rows, rows)
        self.assertEqual(model._rows, frames)
        self.assertEqual(view.selectionModel().selectedRows()[0].row(), 1)
        self.assertIs(self.window.send_panel.entries[0], entry)
        self.assertEqual(entry.period_ms, 123)
        self.assertTrue(self.window.fd_chk.isChecked())
        self.assertTrue(self.window.trace_panel._paused)
        self.assertEqual(send_spy.count(), 0)
        self.assertEqual(model._brush_tx.color(), QColor(style.BG_TX))
        self.assertNotEqual(model.data(model.index(0, model.COL_ID), Qt.ForegroundRole).color(), before_id_color)

    def test_theme_labels_follow_language_switch(self):
        self.switch("dark")
        self.window.act_lang_en.trigger()
        self.assertEqual(self.window.act_theme_dark.text(), "Dark")
        self.assertEqual(self.window.act_theme_light.text(), "Light")
        self.assertTrue(self.window.act_theme_dark.isChecked())
        self.window.act_lang_zh.trigger()
        self.assertEqual(self.window.act_theme_dark.text(), "深色")
        self.assertEqual(style.current_theme(), "dark")

    def test_semantic_text_handles_cached_old_theme_color(self):
        label = QLabel("status", self.window)
        old = style.LOAD_MID
        style.set_text_color(label, old, "font-weight: 600;")
        self.switch("dark")
        self.assertEqual(label.palette().color(QPalette.WindowText), QColor(style.LOAD_MID))
        style.set_text_color(label, old, "font-weight: 600;")
        self.assertEqual(label.palette().color(QPalette.WindowText), QColor(style.LOAD_MID))
        self.assertNotIn(old, label.styleSheet())
        self.assertIn("font-weight", label.styleSheet())

    def test_curve_colors_change_without_losing_history(self):
        single = ValueScope("test", style.FG_ACCENT, parent=self.window)
        dual = TorqueScope(["a", "b"], [style.FG_ACCENT, style.LOAD_MID], parent=self.window)
        single.add_sample(1, 2)
        dual.add_sample(0, 1, 2)
        single.set_paused(True)
        history = list(single._bucket)
        dual_history = list(dual._buckets[0])
        self.switch("dark")
        self.assertEqual(single._color, QColor(style.FG_ACCENT))
        self.assertEqual(dual._colors, [QColor(style.FG_ACCENT), QColor(style.LOAD_MID)])
        self.assertEqual(list(single._bucket), history)
        self.assertEqual(list(dual._buckets[0]), dual_history)
        self.assertTrue(single.is_paused())

    def test_battery_and_power_tables_refresh_existing_cells(self):
        battery = self.activate("battery_monitor")
        power = self.activate("power_monitor")
        data = VoltageData(3, 0, 3, [3300, 3400, 3350])
        battery._on_voltage(data)
        row = next(row for rid, row in power._row_index.items() if not rid.startswith("sec."))
        with patch.object(self.window.plugins._ctx, "send_frame") as send:
            self.switch("dark")
            send.assert_not_called()
        self.assertIs(battery._voltage, data)
        self.assertEqual(battery._cell_table.item(0, 3).foreground().color(), QColor(style.FG_TEXT))
        self.assertEqual(battery._cell_table.item(1, 1).foreground().color(), QColor(style.LOAD_HIGH))
        self.assertEqual(power._table.item(row, 2).foreground().color(), QColor(style.FG_DIM))
        self.assertEqual(battery._status_label.palette().color(QPalette.WindowText), QColor(style.FG_DIM))

    def test_motor_and_torque_controls_keep_state_during_switch(self):
        motor = self.activate("juxie_motor")
        torque = self.activate("torque_sensor")
        keli = self.activate("keli_torque")
        motor._dev_id_spin.setValue(7)
        parameters = self.window._settings.copy()
        with patch.object(self.window.plugins._ctx, "send_frame") as send:
            self.switch("dark")
            self.switch("light")
            send.assert_not_called()
        self.assertEqual(motor._dev_id_spin.value(), 7)
        for key, value in parameters.items():
            if key != "theme":
                self.assertEqual(self.window._settings[key], value)
        self.assertIsNotNone(torque)
        self.assertIsNotNone(keli)

    def test_newly_opened_plugins_use_the_current_theme(self):
        self.switch("dark")
        battery = self.activate("battery_monitor")
        keli = self.activate("keli_torque")
        self.assertEqual(battery._status_label.palette().color(QPalette.WindowText), QColor(style.FG_DIM))
        self.assertEqual(keli._big_value.palette().color(QPalette.WindowText), QColor(style.LOAD_LOW))
        self.assertEqual(keli._scope._color, QColor(style.FG_ACCENT))

    def test_close_preserves_active_plugins_without_a_pending_save(self):
        self.activate("battery_monitor")
        self.switch("dark")
        self.window.close()
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["plugin.active_list"], ["battery_monitor"])
        self.assertFalse(self.window.plugins._save_timer.isActive())

    def test_invalid_saved_theme_falls_back_to_light(self):
        self.window._apply_theme("outdated-theme", persist=False)
        self.assertEqual(style.current_theme(), "light")
        self.assertTrue(self.window.act_theme_light.isChecked())

    def test_all_plugins_fit_default_viewport_in_both_languages_and_themes(self):
        names = {"battery_monitor", "boot_upgrade", "juxie_motor",
                 "keli_torque", "power_monitor", "torque_sensor"}
        self.assertEqual({p.name for p in self.window.plugins._plugins}, names)
        self.window.resize(1400, 850)
        panels = {name: self.activate(name) for name in names}
        for action in (self.window.act_lang_zh, self.window.act_lang_en):
            action.trigger()
            for theme in ("light", "dark"):
                self.switch(theme)
                for name, panel in panels.items():
                    with self.subTest(plugin=name, language=action.text(), theme=theme):
                        self.window._center_tabs.setCurrentWidget(panel)
                        self.app.processEvents()
                        scrolls = panel.findChildren(QScrollArea)
                        if scrolls:
                            scroll = scrolls[0]
                            self.assertLessEqual(scroll.verticalScrollBar().maximum(), 2)
                            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                        self.assertTrue(panel.isVisible())

    def test_plugin_tabs_keep_parameters_history_and_receive_hidden_updates(self):
        battery = self.activate("battery_monitor")
        motor = self.activate("juxie_motor")
        keli = self.activate("keli_torque")
        motor._kp_spin.setValue(8.5)
        motor._sdo_current_spin.setValue(350)
        keli._scope.add_sample(1, 12.5)
        history = list(keli._scope._bucket)
        original_table = battery._cell_table
        battery._detail_tabs.setCurrentIndex(1)
        data = VoltageData(3, 0, 3, [3300, 3400, 3350])
        battery._on_voltage(data)
        with patch.object(self.window.plugins._ctx, "send_frame") as send, \
             patch.object(self.window.plugins._ctx, "start_upgrade") as upgrade:
            for panel in (battery, motor, keli):
                self.window._center_tabs.setCurrentWidget(panel)
                tabs = panel._detail_tabs
                pages = [tabs.widget(i) for i in range(tabs.count())]
                for index in [*range(tabs.count()), 0]:
                    tabs.setCurrentIndex(index)
                    self.app.processEvents()
                    self.assertIs(tabs.currentWidget(), pages[index])
            send.assert_not_called()
            upgrade.assert_not_called()
        self.assertEqual(motor._kp_spin.value(), 8.5)
        self.assertEqual(motor._sdo_current_spin.value(), 350)
        self.assertEqual(list(keli._scope._bucket), history)
        self.assertIs(battery._cell_table, original_table)
        self.assertIs(battery._voltage, data)
        self.assertEqual(battery._cell_table.item(0, 1).text(), "3300")

    def test_disclosures_preserve_values_and_keep_tuning_out_of_common_controls(self):
        motor = self.activate("juxie_motor")
        torque = self.activate("torque_sensor")
        motor._kp_spin.setValue(9.5)
        torque._setid_target_spin.setValue(5)
        for panel in (motor, torque):
            self.window._center_tabs.setCurrentWidget(panel)
            section = panel.findChild(DisclosureSection)
            self.assertIsNotNone(section)
            self.assertTrue(section.body.isHidden())
            with patch.object(self.window.plugins._ctx, "send_frame") as send, \
                 patch.object(self.window.plugins._ctx, "start_upgrade") as upgrade:
                for expanded in (True, False, True, False):
                    section.header.setChecked(expanded)
                    self.app.processEvents()
                    self.assertEqual(section.body.isHidden(), not expanded)
                send.assert_not_called()
                upgrade.assert_not_called()
        tuning = motor.findChild(DisclosureSection)
        self.assertTrue(tuning.body.isAncestorOf(motor._kp_spin))
        self.assertTrue(tuning.body.isAncestorOf(motor._tq_zero_combo))
        self.assertFalse(tuning.body.isAncestorOf(motor._pos_slider))
        self.assertEqual(motor._kp_spin.value(), 9.5)
        self.assertEqual(torque._setid_target_spin.value(), 5)

    def test_plugin_section_titles_follow_language_without_rebuilding_pages(self):
        panels = [self.activate(name) for name in
                  ("battery_monitor", "juxie_motor", "keli_torque", "torque_sensor")]
        for action in (self.window.act_lang_en, self.window.act_lang_zh):
            action.trigger()
            for panel in panels:
                for section, key in getattr(panel, "_sections", getattr(panel, "_titles", [])):
                    self.assertEqual(section.title(), _(key))
                if hasattr(panel, "_detail_tabs"):
                    tabs = panel._detail_tabs
                    for index in range(tabs.count()):
                        self.assertEqual(tabs.tabText(index), tabs.widget(index).title())
                for section in panel.findChildren(DisclosureSection):
                    self.assertEqual(section.header.toolTip(), _("Plugin.ToggleSection"))

    def test_boot_fields_wrap_without_forcing_a_wide_host_window(self):
        self.window.resize(1100, 850)
        boot = self.activate("boot_upgrade")
        self.window.act_lang_en.trigger()
        self.app.processEvents()
        self.assertLessEqual(self.window.width(), 1100)
        for control in (boot._host_id_spin, boot._hw_id_spin, boot._fw_version_spin,
                        boot._frame_size_combo, boot._overall_bar, boot._start_btn,
                        boot._cancel_btn, boot._clear_log_btn):
            self.assertTrue(control.isVisible())
            top_left = control.mapTo(boot, control.rect().topLeft())
            bottom_right = control.mapTo(boot, control.rect().bottomRight())
            self.assertTrue(boot.rect().contains(top_left))
            self.assertTrue(boot.rect().contains(bottom_right))

    def test_flow_toolbar_wraps_and_expands_progress_without_overlap(self):
        panel = QWidget(self.window)
        flow = FlowLayout(panel)
        first, second = QPushButton("First"), QPushButton("Second")
        bar = QProgressBar()
        bar.setMinimumWidth(140)
        for control in (first, bar, second):
            flow.addWidget(control)
        panel.show()
        wide = 700
        flow.setGeometry(panel.rect().adjusted(0, 0, wide - panel.width(), 0))
        wide_height = flow.heightForWidth(wide)
        self.assertGreater(bar.width(), bar.sizeHint().width())
        self.assertGreater(second.x(), bar.geometry().right())
        narrow = max(first.sizeHint().width(), bar.minimumWidth(), second.sizeHint().width())
        self.assertGreater(flow.heightForWidth(narrow), wide_height)


if __name__ == "__main__":
    unittest.main()
