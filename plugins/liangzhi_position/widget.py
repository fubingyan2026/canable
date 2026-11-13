"""Independent CAN Simple position controls for Liangzhi nodes 1 and 2."""
import math
from pathlib import Path
import struct

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from cangui.i18n import _
from cangui.plugin_ui import FlowLayout
from plugins.liangzhi_motor import protocol as can


def tr(key):
    return _("LiangzhiPosition." + key)


def _spin(minimum, maximum, value=0, step=0.01):
    return QDoubleSpinBox(decimals=3, minimum=minimum, maximum=maximum,
                          value=value, singleStep=step, keyboardTracking=False)


def _row(*widgets):
    layout = FlowLayout()
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class AxisPanel(QGroupBox):
    DEFAULT_RATIO = 35.0
    SLIDER_STEPS = 1000
    SLIDER_INTERVAL_MS = 50

    def __init__(self, node, ctx, transport):
        super().__init__()
        self.node = node
        self.ctx = ctx
        self._transport = transport
        self._translations = []
        self._heartbeat = None
        self._position = None
        self._last_target = None
        self._status = None
        self._pending_slider = False
        self._drag_timer = QTimer(self, singleShot=True, interval=self.SLIDER_INTERVAL_MS)
        self._drag_timer.timeout.connect(self._flush_slider)

        root = QVBoxLayout(self)
        self.axis_state = QLabel(wordWrap=True)
        self.feedback = QLabel(wordWrap=True)
        root.addWidget(self.axis_state)
        root.addWidget(self.feedback)
        self.gear_ratio = _spin(0.001, 1e6, self.DEFAULT_RATIO)
        root.addLayout(_row(self._label("GearRatio"), self.gear_ratio))

        self.mode = QComboBox()
        modes = (("Filtered", 3), ("Direct", 1), ("Trapezoidal", 5))
        for key, value in modes:
            self.mode.addItem(f"3 / {value}  {tr(key)}", value)
        self._translations.append(lambda: self._translate_modes(modes))
        root.addLayout(_row(self._label("Mode"), self.mode, self._button("SetMode", self._set_mode)))
        root.addLayout(_row(self._button("ClosedLoop", lambda: self._action(0x07, 8)),
                            self._button("Idle", lambda: self._action(0x07, 1)),
                            self._button("Clear", lambda: self._action(0x18)),
                            self._button("Estop", lambda: self._action(0x02))))

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        radians_per_rotor_turn = math.tau / self.DEFAULT_RATIO
        self.target = _spin(-1e6, 1e6)
        self.velocity = _spin(-1e6, 1e6)
        self.torque = _spin(-32.768, 32.767)
        self.trajectory_speed = _spin(0.001, 1e6, radians_per_rotor_turn, 0.1)
        self.jog_step = _spin(0.001, 1e6, 0.05 * radians_per_rotor_turn)
        form.addRow(self._label("Target"), self.target)
        form.addRow(self._label("Velocity"), self.velocity)
        form.addRow(self._label("Torque"), self.torque)
        form.addRow(self._button("SendTarget", self._send_typed_target))
        form.addRow(self._label("TrajectorySpeed"),
                    _row(self.trajectory_speed, self._button("SetSpeed", self._set_speed)))
        form.addRow(self._label("JogStep"), self.jog_step)
        form.addRow(_row(self._button("JogMinus", lambda: self._jog(-1)),
                         self._button("JogPlus", lambda: self._jog(1))))
        root.addLayout(form)

        self.slider_min = _spin(-1e6, 1e6, -radians_per_rotor_turn)
        self.slider_max = _spin(-1e6, 1e6, radians_per_rotor_turn)
        root.addLayout(_row(self._label("SliderRange"), self.slider_min, self.slider_max))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.SLIDER_STEPS)
        self.slider.setTracking(True)
        self._translations.append(lambda: self.slider.setAccessibleName(tr("Slider")))
        root.addWidget(self._label("Slider"))
        root.addWidget(self.slider)

        self.firmware = QComboBox()
        self.firmware.setMinimumContentsLength(15)
        self.firmware.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.firmware.addItem(tr("ChooseFirmware"), None)
        self._translations.append(lambda: self.firmware.setItemText(0, tr("ChooseFirmware")))
        for path in sorted(can.MANUAL_ASSETS.glob("endpoint*.json")):
            self.firmware.addItem(path.name, path.name)
        root.addLayout(_row(self._label("Firmware"), self.firmware, self._button("ImportFirmware", self._import_firmware)))
        zero = self._button("Zero", self._zero)
        self._translations.append(lambda: zero.setToolTip(tr("ZeroHint")))
        root.addLayout(_row(zero, self._button("SaveDrive", self._save_drive)))

        self.status = QLabel(wordWrap=True)
        root.addWidget(self.status)
        root.addStretch()

        self._settings_key = f"liangzhi_position.axis_{node}"
        self._settings_fields = {
            "gear_ratio": self.gear_ratio, "target_rad": self.target, "velocity_rad_s": self.velocity,
            "torque_nm": self.torque, "trajectory_rad_s": self.trajectory_speed, "jog_rad": self.jog_step,
            "slider_min_rad": self.slider_min, "slider_max_rad": self.slider_max,
        }
        self._restore_settings()
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(self._flush_slider)
        self.target.valueChanged.connect(self._target_edited)
        self.gear_ratio.valueChanged.connect(self._ratio_changed)
        self.slider_min.valueChanged.connect(self._range_changed)
        self.slider_max.valueChanged.connect(self._range_changed)
        self._sync_slider()
        self.refresh_language()

    def _label(self, key):
        label = QLabel(tr(key))
        self._translations.append(lambda: label.setText(tr(key)))
        return label

    def _button(self, key, action):
        button = QPushButton(tr(key))
        button.clicked.connect(action)
        self._translations.append(lambda: button.setText(tr(key)))
        return button

    def _translate_modes(self, modes):
        for index, (key, value) in enumerate(modes):
            self.mode.setItemText(index, f"3 / {value}  {tr(key)}")

    def _set_status(self, key, **values):
        self._status = key, values
        self.status.setText(tr(key).format(**values))

    def _send(self, command, *values):
        return self._send_payload(command, can.command_payload(command, tuple(map(str, values))))

    def _send_payload(self, command, payload):
        if not self.ctx.is_connected():
            self._set_status("Disconnected")
            return False
        transport = self._transport()
        if transport and not self.ctx.is_fd_mode():
            self._set_status("NeedFd")
            return False
        can_id = can.simple_id(self.node, command)
        self.ctx.send_frame(can.frame(can_id, payload, transport))
        self._set_status("Queued", can_id=can_id)
        return True

    def _action(self, command, *values):
        self.cancel_slider()
        if self._send(command, *values) and command in (0x02, 0x07, 0x0B):
            self._last_target = None

    def _set_mode(self):
        self._action(0x0B, 3, self.mode.currentData())

    def _set_speed(self):
        self._action(0x11, self.trajectory_speed.value() * self._rotor_turns_per_rad())

    def _rotor_turns_per_rad(self):
        return self.gear_ratio.value() / math.tau

    def _ratio_changed(self):
        self.cancel_slider()
        self._last_target = None
        self._show_feedback()

    def _send_position(self):
        position = self.target.value()
        factor = self._rotor_turns_per_rad()
        velocity_ff = round(self.velocity.value() * factor * 1000)
        if not -32768 <= velocity_ff <= 32767:
            self._set_status("InvalidVelocity", low=-32.768 / factor, high=32.767 / factor)
            return
        if self._send(0x0C, position * factor, velocity_ff, round(self.torque.value() * 1000)):
            self._last_target = position
            self._set_status("PositionQueued", position=position, can_id=can.simple_id(self.node, 0x0C))

    def _send_typed_target(self):
        self.cancel_slider()
        self._send_position()

    def _jog(self, direction):
        self.cancel_slider()
        base = self._last_target
        if base is None:
            if self._position is None:
                self._set_status("JogNeedsPosition")
                return
            base = self._position[0] / self._rotor_turns_per_rad()
        target = base + direction * self.jog_step.value()
        if not self.target.minimum() <= target <= self.target.maximum():
            self._set_status("InvalidTarget")
            return
        self.target.setValue(target)
        self._send_position()

    def _sync_slider(self):
        low, high = self.slider_min.value(), self.slider_max.value()
        self.slider.setEnabled(high > low)
        if high > low:
            fraction = (min(high, max(low, self.target.value())) - low) / (high - low)
            with QSignalBlocker(self.slider):
                self.slider.setValue(round(self.SLIDER_STEPS * fraction))

    def _target_edited(self):
        self.cancel_slider()
        self._sync_slider()

    def _range_changed(self):
        self.cancel_slider()
        self._sync_slider()
        if not self.slider.isEnabled():
            self._set_status("InvalidRange")
        elif self._status and self._status[0] == "InvalidRange":
            self._status = None
            self.status.clear()

    def _slider_changed(self, value):
        low, high = self.slider_min.value(), self.slider_max.value()
        if high <= low:
            return
        with QSignalBlocker(self.target):
            self.target.setValue(low + (high - low) * value / self.SLIDER_STEPS)
        self._pending_slider = True
        if not self.slider.isSliderDown():
            self._flush_slider()
        elif not self._drag_timer.isActive():
            self._drag_timer.start()

    def _flush_slider(self):
        self._drag_timer.stop()
        if self._pending_slider:
            self._pending_slider = False
            self._send_position()

    def cancel_slider(self):
        self._pending_slider = False
        self._drag_timer.stop()

    def _restore_settings(self):
        saved = self.ctx.get_setting(self._settings_key, {})
        if not isinstance(saved, dict):
            return
        for key, editor in self._settings_fields.items():
            value = saved.get(key)
            if type(value) in (float, int) and editor.minimum() <= value <= editor.maximum():
                editor.setValue(value)
        mode = self.mode.findData(saved.get("mode"))
        if mode >= 0:
            self.mode.setCurrentIndex(mode)
        source = saved.get("firmware")
        if isinstance(source, str) and source:
            self._select_firmware(source)

    def save_settings(self):
        values = {key: editor.value() for key, editor in self._settings_fields.items()}
        values.update(mode=self.mode.currentData(), firmware=self.firmware.currentData())
        self.ctx.set_setting(self._settings_key, values)

    def _select_firmware(self, source):
        index = self.firmware.findData(source)
        if index < 0:
            self.firmware.addItem(Path(source).name, source)
            index = self.firmware.count() - 1
        self.firmware.setCurrentIndex(index)

    def _import_firmware(self):
        filename, _selected_filter = QFileDialog.getOpenFileName(self, tr("ImportFirmware"), "", "*.json")
        if filename:
            self._select_firmware(filename)

    def _zero(self):
        self.cancel_slider()
        source = self.firmware.currentData()
        if source is None:
            self._set_status("NeedFirmware")
            return
        try:
            endpoints = can.load_endpoints(can.MANUAL_ASSETS / source)
            zero = next((entry for entry in endpoints if entry.function and
                         entry.name.rsplit(".", 1)[-1] == "set_current_pos_zero"), None)
            if zero is None:
                self._set_status("ZeroUnavailable")
                return
            payload = can.endpoint_payload(zero.index)
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            self._set_status("InvalidFirmware", name=Path(source).name)
            return
        if self._send_payload(0x04, payload):
            self._last_target = self._position = None
            self._show_feedback()
            self._set_status("ZeroQueued", can_id=can.simple_id(self.node, 0x04))

    def _save_drive(self):
        self.cancel_slider()
        if self._send(0x1F):
            self.reset_feedback()
            self._set_status("DriveSaveQueued", can_id=can.simple_id(self.node, 0x1F))

    def reset_feedback(self):
        self.cancel_slider()
        self._heartbeat = self._position = self._last_target = self._status = None
        self.status.clear()
        self._show_feedback()

    def receive(self, command, data):
        if command == 0x01:
            self._heartbeat = struct.unpack_from("<IB", data)
        elif command == 0x09:
            position = struct.unpack("<ff", data)
            if all(map(math.isfinite, position)):
                self._position = position

    def _show_feedback(self):
        if self._heartbeat is None:
            self.axis_state.setText(tr("Waiting"))
        else:
            error, state = self._heartbeat
            label = {1: "StateIdle", 8: "StateClosed"}.get(state)
            self.axis_state.setText(tr("AxisState").format(state=tr(label) if label else state, error=error))
        if self._position is None:
            self.feedback.clear()
        else:
            factor = self._rotor_turns_per_rad()
            self.feedback.setText(tr("Feedback").format(position=self._position[0] / factor,
                                                        velocity=self._position[1] / factor))

    def refresh_language(self):
        self.setTitle(tr("Motor").format(node=self.node))
        for translate in self._translations:
            translate()
        self._show_feedback()
        if self._status:
            self._set_status(self._status[0], **self._status[1])


class PositionPanel(QWidget):
    TRANSPORTS = ("Classic", "Fd", "Brs")
    TRANSPORT_KEY = "liangzhi_position.transport"

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        self.transport_label = QLabel()
        self.transport = QComboBox()
        for index, key in enumerate(self.TRANSPORTS):
            self.transport.addItem(tr(key), index)
        saved = ctx.get_setting(self.TRANSPORT_KEY, 0)
        self.transport.setCurrentIndex(saved if type(saved) is int and 0 <= saved < self.transport.count() else 0)
        self.transport.currentIndexChanged.connect(self._transport_changed)
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self._save_settings)
        self.save_status = QLabel()
        root.addLayout(_row(self.transport_label, self.transport, self.save_button, self.save_status))
        columns = QHBoxLayout()
        self.axes = {node: AxisPanel(node, ctx, self.transport.currentData) for node in (1, 2)}
        for axis in self.axes.values():
            columns.addWidget(axis, 1)
        root.addLayout(columns, 1)
        self.refresh_language()

    def _transport_changed(self, index):
        self.ctx.set_setting(self.TRANSPORT_KEY, index)
        self.reset_feedback()

    def _save_settings(self):
        for axis in self.axes.values():
            axis.save_settings()
        self.save_status.setText(tr("SettingsSaved"))

    def reset_feedback(self):
        for axis in self.axes.values():
            axis.reset_feedback()

    def on_frames(self, frames):
        updated = set()
        for frame in frames:
            if frame.is_tx or frame.is_error or frame.rtr or frame.extended or len(frame.data) != 8:
                continue
            node, command = divmod(frame.can_id, 0x20)
            if node in self.axes and command in (0x01, 0x09):
                self.axes[node].receive(command, frame.data)
                updated.add(node)
        for node in updated:
            self.axes[node]._show_feedback()

    def refresh_language(self):
        self.transport_label.setText(tr("Transport"))
        self.save_button.setText(tr("SaveSettings"))
        if self.save_status.text():
            self.save_status.setText(tr("SettingsSaved"))
        for index, key in enumerate(self.TRANSPORTS):
            self.transport.setItemText(index, tr(key))
        for axis in self.axes.values():
            axis.refresh_language()
