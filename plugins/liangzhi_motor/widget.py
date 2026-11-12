"""Native Qt controls for Liangzhi motors, using the host CAN connection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cangui.i18n import _
from cangui.plugin_ui import FlowLayout
from . import faults
from . import protocol as p


def tr(key):
    return _("Liangzhi." + key)


@dataclass
class CyclicMit:
    payload: bytes
    period: float
    due: float


@dataclass(frozen=True)
class Request:
    can_id: int
    parameter: p.Parameter
    open_protocol: bool
    write: bool = False


class MotorPanel(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._translations = []
        self._cycles: dict[int, CyclicMit] = {}
        self._mit_limits: dict[int, p.MitLimits] = {}
        self._request: Request | None = None
        self._fault_query: tuple[int, float] | None = None
        self._feedback: dict[str, str | faults.Reading] = {}
        self._status = ("Ready", {})
        self._protocol_is_open = False
        self._cycle_timer = QTimer(self, timerType=Qt.TimerType.PreciseTimer, interval=2)
        self._cycle_timer.timeout.connect(self._send_due)
        self._response_timer = QTimer(self, singleShot=True, interval=1200)
        self._response_timer.timeout.connect(self._response_timeout)

        root = QVBoxLayout(self)
        header = FlowLayout()
        self.node = QSpinBox(minimum=0, maximum=63)
        self.node.setValue(self._setting_int("node", 1, 63))
        self.transport = QComboBox()
        for index, key in enumerate(("Classic", "Fd", "Brs")):
            self._combo_item(self.transport, key, index)
        self.transport.setCurrentIndex(self._setting_int("transport", 0, 2))
        self._translations.append(lambda: self.transport.setToolTip(tr("TransportHint")))
        for item in (self._label("Node"), self.node, self._label("Transport"), self.transport):
            header.addWidget(item)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.status = QLabel(wordWrap=True)
        root.addWidget(self.tabs)
        simple = self._page("Simple")
        self._build_simple(simple)
        mit = self._page("Mit")
        self._build_mit(mit)
        endpoints = self._page("Endpoints")
        self._build_parameters(endpoints, False)
        canopen = self._page("Open")
        self._build_canopen(canopen)
        self.open_tab = self.tabs.count() - 1

        root.addWidget(self.status)
        self.table = QTableWidget(0, 2)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.node.valueChanged.connect(self._node_changed)
        self.transport.currentIndexChanged.connect(self._transport_changed)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.refresh_language()

    def _setting_int(self, name, default, maximum):
        value = self.ctx.get_setting(f"liangzhi_motor.{name}", default)
        return value if type(value) is int and 0 <= value <= maximum else default

    def _label(self, key):
        label = QLabel(tr(key))
        self._translations.append(lambda: label.setText(tr(key)))
        return label

    def _button(self, key, callback):
        button = QPushButton(tr(key))
        button.clicked.connect(callback)
        self._translations.append(lambda: button.setText(tr(key)))
        return button

    def _combo_item(self, combo, key, value, prefix=""):
        index = combo.count()
        combo.addItem(prefix + tr(key), value)
        self._translations.append(lambda: combo.setItemText(index, prefix + tr(key)))

    def _page(self, key):
        page = QWidget()
        layout = QVBoxLayout(page)
        index = self.tabs.addTab(page, tr(key))
        self._translations.append(lambda: self.tabs.setTabText(index, tr(key)))
        return layout

    @staticmethod
    def _row(layout, *widgets):
        row = FlowLayout()
        for widget in widgets:
            row.addWidget(widget)
        layout.addLayout(row)

    def _build_simple(self, layout):
        self.command = QComboBox()
        for code in sorted(p.COMMANDS.keys() | p.TELEMETRY.keys() | {1}):
            key = f"Command.{code}" if code in p.COMMANDS else (
                "Heartbeat" if code == 1 else p.TELEMETRY[code][0])
            self._combo_item(self.command, key, code, f"0x{code:02X}  ")
        self.command.setCurrentIndex(self.command.findData(7))
        self._row(layout, self._label("Command"), self.command,
                  self._button("Send", self._send_command),
                  self._button("Idle", lambda: self._send_simple(7, ("1",))),
                  self._button("Estop", lambda: self._send_simple(2)))
        self.command_form = QFormLayout()
        layout.addLayout(self.command_form)
        self.command.currentIndexChanged.connect(self._show_command)
        self._show_command()
        layout.addStretch()

    def _show_command(self):
        while self.command_form.rowCount():
            self.command_form.removeRow(0)
        self.command_inputs = []
        code = self.command.currentData()
        if code not in p.COMMANDS:
            self.command_form.addRow(QLabel(tr("RtrHint"), wordWrap=True))
            return
        command = p.COMMANDS[code]
        enum_fields = {3: (p.ERROR_TYPES,), 7: (p.AXIS_STATES,), 11: (p.CONTROL_MODES, p.INPUT_MODES)}
        for index, field in enumerate(command.fields):
            if code in enum_fields:
                editor = QComboBox()
                prefix = {3: "Error", 7: "Axis", 11: ("Control", "Input")[index]}[code]
                for value in enum_fields[code][index]:
                    editor.addItem(f"{value}  {tr(f'{prefix}.{value}')}", value)
                if code == 7:
                    editor.setCurrentIndex(editor.findData(1))
            else:
                editor = QLineEdit("0")
            self.command_form.addRow(tr(f"Field.{field}"), editor)
            self.command_inputs.append(editor)

    def _send_command(self):
        code = self.command.currentData()
        if code not in p.COMMANDS:
            if self.transport.currentData() != 0:
                self._set_status("RtrClassic")
                return
            self._perform(lambda: p.frame(p.simple_id(self.node.value(), code), bytes(8), rtr=True))
            return
        values = tuple(str(item.currentData()) if isinstance(item, QComboBox) else item.text()
                       for item in self.command_inputs)
        self._send_simple(code, values)

    def _send_simple(self, code, values=()):
        node = self.node.value()
        if code == 3 and self._fault_query is not None and time.monotonic() < self._fault_query[1]:
            self._set_status("FaultBusy")
            return
        if self._perform(lambda: p.frame(p.simple_id(node, code), p.command_payload(code, values),
                                         self.transport.currentData())):
            if code == 3:
                self._fault_query = (int(p.number(values[0], "B")), time.monotonic() + 1.2)
            else:
                self._stop_cycle(node)

    def _build_mit(self, layout):
        hint = self._label("MitHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        targets, limits = QFormLayout(), QFormLayout()
        self.targets = []
        self.limit_edits = []
        defaults = p.MitLimits()
        for key, value in zip(("Position", "Velocity", "Kp", "Kd", "Torque"),
                              (defaults.position, defaults.velocity, defaults.kp, defaults.kd, defaults.torque)):
            target = QDoubleSpinBox(decimals=6, minimum=-1e6, maximum=1e6)
            limit = QDoubleSpinBox(decimals=6, minimum=0.000001, maximum=1e6, value=value)
            targets.addRow(self._label("TorqueTarget" if key == "Torque" else key), target)
            limits.addRow(self._label("Max" + key), limit)
            self.targets.append(target)
            self.limit_edits.append(limit)
            limit.valueChanged.connect(self._save_limits)
        controls.addLayout(targets)
        controls.addLayout(limits)
        layout.addLayout(controls)
        self.period = QSpinBox(minimum=2, maximum=10000, value=20, suffix=" ms")
        self._row(layout, self._button("SetMit", lambda: self._send_simple(0x0B, ("3", "9"))),
                  self._button("ClosedLoop", lambda: self._send_simple(7, ("8",))),
                  self._button("Idle", lambda: self._send_simple(7, ("1",))),
                  self._button("Send", lambda: self._send_mit(False)))
        self._row(layout, self._label("Period"), self.period,
                  self._button("StartCycle", lambda: self._send_mit(True)),
                  self._button("StopCycle", self._stop_selected),
                  self._button("StopAll", self._stop_all_clicked))
        self.cycle_label = QLabel()
        layout.addWidget(self.cycle_label)

    def _save_limits(self):
        node = self.node.value()
        self._mit_limits[node] = p.MitLimits(*(edit.value() for edit in self.limit_edits))
        self._stop_cycle(node)

    def _send_mit(self, repeat):
        node = self.node.value()
        try:
            payload = p.mit_payload(tuple(editor.value() for editor in self.targets),
                                    self._mit_limits.get(node, p.MitLimits()))
        except ValueError as exc:
            self._set_status("Invalid", detail=str(exc))
            return
        if self._perform(lambda: p.frame(p.simple_id(node, 8), payload, self.transport.currentData())):
            if repeat:
                period = self.period.value() / 1000
                self._cycles[node] = CyclicMit(payload, period, time.monotonic() + period)
                if not self._cycle_timer.isActive():
                    self._cycle_timer.start()
                self._refresh_cycles()
            else:
                self._stop_cycle(node)

    def _send_due(self):
        if not self._connection_ok():
            self.stop()
            return
        now = time.monotonic()
        transport = self.transport.currentData()
        for node, cycle in self._cycles.items():
            if now >= cycle.due:
                self.ctx.send_frame(p.frame(p.simple_id(node, 8), cycle.payload, transport))
                cycle.due = now + cycle.period

    def _stop_cycle(self, node):
        if self._cycles.pop(node, None) is not None:
            if not self._cycles:
                self._cycle_timer.stop()
            self._refresh_cycles()

    def _stop_selected(self):
        self._stop_cycle(self.node.value())
        self._set_status("Stopped")

    def _stop_all_clicked(self):
        self.stop()
        self._set_status("Stopped")

    def _refresh_cycles(self):
        self.cycle_label.setText(tr("Running").format(nodes=", ".join(map(str, sorted(self._cycles))) or "—"))

    def _build_parameters(self, layout, is_open):
        selector = QComboBox()
        selector.setMinimumContentsLength(28)
        selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        search = QLineEdit()
        search.setPlaceholderText(tr("Search"))
        self._translations.append(lambda: search.setPlaceholderText(tr("Search")))
        value = QLineEdit()
        source = QLabel(wordWrap=True)
        manual = QLineEdit()
        manual.setMaximumWidth(145)
        self._translations.append(lambda: manual.setPlaceholderText(tr("ManualAddress")))
        kinds = QComboBox()
        for kind, fmt in p.ENDPOINT_FORMATS.items():
            kinds.addItem(kind, fmt)
        kinds.setCurrentIndex(kinds.findData("I"))
        mode = "eds" if is_open else "json"
        defaults = QComboBox()
        paths = ([p.MANUAL_ASSETS / "ds402.eds"] if is_open else
                 sorted(p.MANUAL_ASSETS.glob("endpoint*.json")))
        self._combo_item(defaults, "ChooseTable", None)
        for path in paths:
            if path.is_file():
                defaults.addItem(path.name, path)
        entries = []

        def refill():
            old = selector.currentData()
            text = search.text().strip().casefold()
            selector.clear()
            for entry in entries:
                address = f"0x{entry.index:04X}:{entry.sub:02X}" if is_open else f"0x{entry.index:04X}"
                label = f"{address}  {entry.name}"
                if text in label.casefold():
                    selector.addItem(label, entry)
            if old in entries:
                index = selector.findData(old)
                if index >= 0:
                    selector.setCurrentIndex(index)

        def load(path):
            if path is None:
                return
            try:
                params = (p.load_eds if is_open else p.load_endpoints)(path)
            except (OSError, ValueError, KeyError, TypeError, struct.error, p.configparser.Error) as exc:
                self._set_status("Invalid", detail=str(exc))
                return
            if not params:
                self._set_status("NoEntries")
                return
            entries[:] = params
            source.setText(path.name)
            manual.clear()
            value.clear()
            search.clear()
            refill()

        def choose_file():
            filename, _selected = QFileDialog.getOpenFileName(self, tr("Load"), "", f"*.{mode}")
            if filename:
                load(Path(filename))

        def access(write=False, invoke=False):
            param = selector.currentData()
            address = manual.text().strip()
            if address:
                try:
                    index, separator, sub = address.partition(":")
                    if separator and not is_open:
                        raise ValueError("Endpoint IDs have no subindex")
                    param = p.Parameter(address, int(index, 16), "rw", kinds.currentData(),
                                        int(sub, 16) if separator else 0, invoke)
                except ValueError as exc:
                    self._set_status("Invalid", detail=str(exc))
                    return
            self._parameter(param, value.text() if write else None, is_open, invoke)

        def zero():
            param = next((item for item in entries if item.function and
                          item.name.rsplit(".", 1)[-1] == "set_current_pos_zero"), None)
            if param is None:
                self._set_status("ZeroUnavailable")
                return
            self._parameter(param, None, False, True)

        defaults.activated.connect(lambda: load(defaults.currentData()))
        search.textChanged.connect(refill)
        selector.currentIndexChanged.connect(value.clear)
        selector.activated.connect(manual.clear)
        manual.textChanged.connect(value.clear)
        kinds.currentIndexChanged.connect(value.clear)
        self._row(layout, self._label("Table"), defaults, self._button("Load", choose_file))
        layout.addWidget(source)
        self._row(layout, search, selector)
        self._row(layout, manual, kinds)
        self._row(layout, self._label("Value"), value,
                  self._button("Read", lambda: access()), self._button("Write", lambda: access(write=True)))
        if is_open:
            if defaults.count() > 1:
                defaults.setCurrentIndex(1)
                load(defaults.currentData())
        else:
            self._row(layout, self._button("Call", lambda: access(invoke=True)), self._button("Zero", zero),
                      self._button("Save", lambda: self._send_simple(0x1F)))
            layout.addStretch()

    def _parameter(self, param, value, is_open, invoke=False):
        if param is None:
            self._set_status("ChooseParameter")
            return
        if invoke != param.function or (not invoke and ("r" if value is None else "w") not in param.access):
            self._set_status("Access")
            return
        if self._request is not None:
            self._set_status("Busy")
            return
        node = self.node.value()

        def build():
            data = None if value is None else p.parameter_value(param, value)
            if is_open:
                return p.frame(0x600 + self._open_node(), p.sdo_payload(param.index, param.sub, data),
                               self.transport.currentData())
            return p.frame(p.simple_id(node, 4), p.endpoint_payload(param.index, data),
                           self.transport.currentData())

        if self._perform(build):
            if value is not None or invoke:
                self._stop_cycle(node)
            if is_open or (value is None and not invoke):
                can_id = 0x580 + node if is_open else p.simple_id(node, 5)
                self._request = Request(can_id, param, is_open, value is not None)
                self._response_timer.start()

    def _build_canopen(self, layout):
        nmt = QComboBox()
        for cmd in (1, 2, 0x80, 0x81, 0x82):
            self._combo_item(nmt, f"Nmt.{cmd}", cmd)
        broadcast = QCheckBox()
        self._translations.append(lambda: broadcast.setText(tr("Broadcast")))
        self._row(layout, self._label("Nmt"), nmt, broadcast,
                  self._button("Send", lambda: self._open_send(
                      0, lambda: bytes((nmt.currentData(), 0 if broadcast.isChecked() else self._open_node())))),
                  self._button("Sync", lambda: self._open_send(0x80, bytes)))
        control = QComboBox()
        for value in (0, 6, 7, 15, 2, 128):
            self._combo_item(control, f"Servo.{value}", value, f"0x{value:02X}  ")
        word = p.Parameter("Controlword (0x6040)", 0x6040, "rw", "H")
        status = p.Parameter("Statusword (0x6041)", 0x6041, "r", "H")
        self._row(layout, self._label("Servo"), control,
                  self._button("Send", lambda: self._parameter(word, str(control.currentData()), True)),
                  self._button("ReadServo", lambda: self._parameter(status, None, True)))
        pdo = QComboBox()
        for index in range(1, 5):
            pdo.addItem(f"RPDO {index}", 0x100 + 0x100 * index)
        payload = QLineEdit()
        payload.setPlaceholderText("0F 00 00 40 00 00")
        cob_id = QLineEdit()
        cob_id.setPlaceholderText(tr("DefaultId"))
        self._translations.append(lambda: cob_id.setPlaceholderText(tr("DefaultId")))

        def send_pdo():
            self._perform(lambda: p.frame(int(cob_id.text(), 16) if cob_id.text().strip()
                                          else pdo.currentData() + self._open_node(),
                                          self._pdo_bytes(payload.text()), self.transport.currentData()))

        self._row(layout, pdo, cob_id, payload, self._button("SendPdo", send_pdo))
        self._build_parameters(layout, True)
        layout.addStretch()

    @staticmethod
    def _pdo_bytes(text):
        payload = bytes.fromhex(text)
        if len(payload) > 8:
            raise ValueError("CANopen PDO must contain at most 8 bytes")
        return payload

    def _open_send(self, can_id, data):
        self._perform(lambda: p.frame(can_id, data(), self.transport.currentData()))

    def _open_node(self):
        node = self.node.value()
        if not 1 <= node <= 127:
            raise ValueError("CANopen node ID must be 1–127")
        return node

    def _connection_ok(self):
        if not self.ctx.is_connected():
            self._set_status("Disconnected")
            return False
        if self.transport.currentData() and not self.ctx.is_fd_mode():
            self._set_status("NeedFd")
            return False
        return True

    def _perform(self, build):
        if not self._connection_ok():
            return False
        try:
            frame = build()
        except (ValueError, OverflowError, struct.error) as exc:
            self._set_status("Invalid", detail=str(exc))
            return False
        self.ctx.send_frame(frame)
        self._set_status("Queued", can_id=frame.can_id, data=frame.data.hex(" ").upper() or "—")
        return True

    def _set_status(self, key, **values):
        self._status = (key, values)
        self.status.setText(tr(key).format(**values))

    def _response_timeout(self):
        self._request = None
        self._set_status("Timeout")

    def _clear_feedback(self):
        self._request = None
        self._response_timer.stop()
        self._fault_query = None
        self._feedback.clear()
        self._render_feedback()

    def _tab_changed(self, index):
        is_open = index == self.open_tab
        if is_open == self._protocol_is_open:
            return
        self._protocol_is_open = is_open
        minimum, maximum = (1, 127) if is_open else (0, 63)
        self.node.blockSignals(True)
        self.node.setRange(minimum, maximum)
        self.node.setValue(self._setting_int(self._node_setting(), 1, maximum))
        self.node.blockSignals(False)
        if is_open:
            self.stop()
        self._node_changed(self.node.value())

    def _node_setting(self):
        return "canopen_node" if self._protocol_is_open else "node"

    def _node_changed(self, node):
        self.ctx.set_setting(f"liangzhi_motor.{self._node_setting()}", node)
        limits = self._mit_limits.get(node, p.MitLimits())
        for editor, value in zip(self.limit_edits, (limits.position, limits.velocity, limits.kp, limits.kd, limits.torque)):
            editor.blockSignals(True)
            editor.setValue(value)
            editor.blockSignals(False)
        for editor in self.targets:
            editor.setValue(0)
        self._clear_feedback()

    def _transport_changed(self, index):
        self.ctx.set_setting("liangzhi_motor.transport", index)
        self.stop()
        self._clear_feedback()

    def stop(self):
        self._cycles.clear()
        self._cycle_timer.stop()
        self._refresh_cycles()

    def on_disconnect(self):
        self.stop()
        self._clear_feedback()
        self._set_status("Disconnected")

    def on_connect(self):
        self._clear_feedback()
        self._set_status("Ready")

    def _parameter_reply(self, frame):
        request = self._request
        if request is None or frame.can_id != request.can_id or len(frame.data) != 8:
            return
        param = request.parameter
        code, index, sub = struct.unpack_from("<BHB", frame.data)
        if index != param.index or (request.open_protocol and sub != param.sub):
            return
        if request.open_protocol:
            if code == 0x80:
                self._set_status("Abort", code=int.from_bytes(frame.data[4:8], "little"))
            elif request.write and code == 0x60:
                self._set_status("Written", name=param.name)
            elif not request.write and code in (0x43, 0x47, 0x4B, 0x4F):
                if 4 - ((code >> 2) & 3) != struct.calcsize("<" + param.fmt):
                    self._set_status("SizeMismatch")
                else:
                    self._show_value(param, frame.data)
            else:
                return
        elif code == 0:
            self._show_value(param, frame.data)
        else:
            return
        self._request = None
        self._response_timer.stop()

    def _show_value(self, param, data):
        value = struct.unpack_from("<" + param.fmt, data, 4)[0]
        self._set_status("ReadValue", name=param.name, value=self._format_number(value))

    @staticmethod
    def _format_number(value):
        return f"{value:.7g}" if isinstance(value, float) else str(int(value))

    def on_frames(self, frames):
        node = self.node.value()
        is_open = self.tabs.currentIndex() == self.open_tab
        updates = {}
        for frame in frames:
            if frame.is_tx or frame.is_error or frame.rtr or frame.extended:
                continue
            self._parameter_reply(frame)
            if is_open:
                self._open_feedback(node, frame, updates)
            elif frame.can_id >> 5 == node:
                self._simple_feedback(node, frame.can_id & 0x1F, frame.data, updates)
        if updates:
            self._feedback.update(updates)
            self._render_feedback()

    def _simple_feedback(self, node, code, data, updates):
        if len(data) != 8 and (code != 3 or len(data) != 4):
            return
        if code == 1:
            error, state, flags, temp, life = struct.unpack("<IBBbB", data)
            updates["Heartbeat"] = f"Axis={state}  Error=0x{error:08X}  Flags=0x{flags:02X}  {temp} °C  Life={life}"
            updates["AxisFault"] = faults.Reading("Axis", error)
            updates["HeartbeatFaultFlags"] = faults.Reading("Flags", flags & 0x0F)
        elif code == 8:
            values = p.mit_feedback(data, node, self._mit_limits.get(node, p.MitLimits()))
            if values is not None:
                pos, vel, torque, flags, temp = values
                updates["MitFeedback"] = f"{pos:.5f} rad  /  {vel:.4f} rad/s  /  {torque:.4f} Nm  /  0x{flags:02X}  /  {temp} °C"
                updates["MitFaultFlags"] = faults.Reading("Flags", flags & 0x0F)
        elif code == 3:
            updates["ErrorDetail"] = self._read_detailed_fault(data)
        elif code in p.TELEMETRY:
            key, fmt, units = p.TELEMETRY[code]
            values = struct.unpack("<" + fmt, data)
            updates[key] = "  /  ".join(f"{self._format_number(value)} {unit}" for value, unit in zip(values, units))

    def _read_detailed_fault(self, data):
        if self._fault_query is not None:
            kind, deadline = self._fault_query
            if time.monotonic() < deadline:
                size = 8 if kind == 0 else 4
                if len(data) >= size:
                    self._fault_query = None
                    return faults.Reading(faults.DETAIL_SOURCE[kind], int.from_bytes(data[:size], "little"))
            else:
                self._fault_query = None
        return data.hex(" ").upper()

    @staticmethod
    def _fault_text(reading: faults.Reading) -> str:
        source = reading.source
        lines = [f"{tr(f'FaultSource.{source}')}  0x{reading.mask:0{reading.width}X}"]
        if not reading.mask:
            lines.append(tr("NoFault"))
        else:
            known, unknown = reading.split()
            for bit, symbol in known:
                description = tr(f"Fault.{source}.{symbol}")
                lines.append(f"0x{bit:X} {symbol}  {description}")
            if unknown:
                lines.append(tr("UnknownFaultBits").format(mask=unknown))
        return "\n".join(lines)

    @staticmethod
    def _open_feedback(node, frame, updates):
        if frame.can_id == 0x700 + node and len(frame.data) == 1:
            updates["Nmt"] = f"0x{frame.data[0]:02X}"
        elif frame.can_id == 0x580 + node and len(frame.data) == 8:
            updates["Sdo"] = frame.data.hex(" ").upper()
        elif frame.can_id - node in (0x180, 0x280, 0x380, 0x480) and len(frame.data) <= 8:
            index = (frame.can_id - node - 0x180) // 0x100 + 1
            updates[f"Tpdo{index}"] = frame.data.hex(" ").upper() or "—"

    def _render_feedback(self):
        self.table.setRowCount(len(self._feedback))
        for row, (key, value) in enumerate(self._feedback.items()):
            if isinstance(value, faults.Reading):
                value = self._fault_text(value)
            for column, text in enumerate((tr(key), value)):
                item = self.table.item(row, column)
                if item is None:
                    self.table.setItem(row, column, QTableWidgetItem(text))
                elif item.text() != text:
                    item.setText(text)

    def refresh_language(self):
        values = [item.currentData() if isinstance(item, QComboBox) else item.text()
                  for item in self.command_inputs]
        for update in self._translations:
            update()
        self._show_command()
        for item, value in zip(self.command_inputs, values):
            if isinstance(item, QComboBox):
                item.setCurrentIndex(item.findData(value))
            else:
                item.setText(value)
        self._refresh_cycles()
        self._set_status(self._status[0], **self._status[1])
        self.table.setHorizontalHeaderLabels((tr("Feedback"), tr("Value")))
        self._render_feedback()
