"""合壹电池 BMS 数据监视面板。

接收 0x0001/0x0002/0x0003 多帧响应 → 组装 → 解析 → 显示：
总览（SOC/总压/电流）、单体电压表、温度、保护与告警、MOS/版本、电池编号，
并保留最近若干包的原始 HEX 供核对。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QGroupBox,
                                QHBoxLayout, QHeaderView, QLabel,
                                QPlainTextEdit, QPushButton, QScrollArea,
                                QSpinBox, QTableWidget, QTableWidgetItem,
                                QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style

from . import protocol as P

logger = logging.getLogger("plugin.battery_monitor")

_OK = style.LOAD_LOW
_WARN = style.LOAD_MID
_ERR = style.LOAD_HIGH
_DIM = style.FG_DIM
_TEXT = style.FG_TEXT

STALE_S = 2.0          # 超过该时间没有响应视为离线
RAW_MAX_LINES = 80     # 原始报文日志上限


# ── i18n ──
_I18N_KEYS = {
    "Batt.Title":           ("电池监视",          "Battery Monitor"),
    "Batt.DevConfig":       ("电池配置",          "Battery Config"),
    "Batt.Addr":            ("地址",              "Address"),
    "Batt.AutoPoll":        ("定时轮询",          "Auto Poll"),
    "Batt.PollInterval":    ("间隔",              "Interval"),
    "Batt.CurrentOffset":   ("电流偏置",          "Current Offset"),
    "Batt.OffsetRaw":       ("偏置(raw)",         "Offset (raw)"),
    "Batt.Refresh":         ("刷新",              "Refresh"),
    "Batt.Online":          ("在线",              "Online"),
    "Batt.Offline":         ("无响应",            "No response"),
    "Batt.UpdatedAt":       ("更新于",            "Updated at"),
    "Batt.NotConnected":    ("CAN 未连接，请先在主界面连接设备",
                             "CAN not connected. Connect a device first."),
    "Batt.Hint.Bitrate":    ("提示：合壹电池为 CAN 2.0 / 250 kbps，请确认波特率",
                             "Hint: this BMS uses CAN 2.0 @ 250 kbps; check the bitrate"),
    "Batt.NoData":          ("—",                 "—"),

    "Batt.Overview":        ("总览",              "Overview"),
    "Batt.Soc":             ("SOC",               "SOC"),
    "Batt.PackVoltage":     ("总电压",            "Pack Voltage"),
    "Batt.Current":         ("电流",              "Current"),
    "Batt.MaxCell":         ("最高单体",          "Max Cell"),
    "Batt.MinCell":         ("最低单体",          "Min Cell"),
    "Batt.DeltaCell":       ("压差",              "Cell Delta"),
    "Batt.Cycles":          ("循环次数",          "Cycles"),
    "Batt.RemainCap":       ("剩余容量",          "Remaining"),
    "Batt.DesignCap":       ("设计容量",          "Design Cap"),
    "Batt.DischargeTime":   ("放电剩余",          "Discharge Left"),
    "Batt.ChargeTime":      ("充电剩余",          "Charge Left"),
    "Batt.Unit.V":          ("V",                 "V"),
    "Batt.Unit.A":          ("A",                 "A"),
    "Batt.Unit.mV":         ("mV",                "mV"),
    "Batt.Unit.Pct":        ("%",                 "%"),
    "Batt.Unit.Ah":         ("Ah",                "Ah"),
    "Batt.Unit.Min":        ("min",               "min"),
    "Batt.Unit.Times":      ("次",                "times"),
    "Batt.Unit.C":          ("℃",                 "℃"),

    "Batt.Cells":           ("单体电压",          "Cell Voltages"),
    "Batt.CellNo":          ("串号",              "Cell"),
    "Batt.CellSummary":     ("最高 {mx} mV（第 {mxi} 串）· 最低 {mn} mV（第 {mni} 串）· 压差 {d} mV",
                             "Max {mx} mV (#{mxi}) · Min {mn} mV (#{mni}) · Delta {d} mV"),

    "Batt.Temps":           ("温度",              "Temperatures"),
    "Batt.CellTemps":       ("电芯温度",          "Cell Temps"),
    "Batt.MosTemp":         ("MOS 温度",          "MOS Temp"),
    "Batt.AmbientTemp":     ("环境温度",          "Ambient Temp"),
    "Batt.MaxTemp":         ("最高温度",          "Max Temp"),

    "Batt.Protect":         ("保护与告警",        "Protection & Alarms"),
    "Batt.Flags":           ("状态",              "Status"),
    "Batt.Discharging":     ("放电中",            "Discharging"),
    "Batt.Charging":        ("充电中",            "Charging"),
    "Batt.Idle":            ("静置",              "Idle"),
    "Batt.KeyOn":           ("KeyON",             "KeyON"),
    "Batt.MosState":        ("MOS 状态",          "MOS State"),
    "Batt.MosDischargeOn":  ("放电 MOS 开",       "Discharge MOS on"),
    "Batt.MosChargeOn":     ("充电 MOS 开",       "Charge MOS on"),
    "Batt.Failure":         ("失效状态",          "Failure"),
    "Batt.SwVersion":       ("软件版本",          "SW Version"),
    "Batt.HwVersion":       ("硬件版本",          "HW Version"),
    "Batt.BatteryId":       ("电池编号",          "Battery ID"),

    "Batt.Raw":             ("原始报文",          "Raw Frames"),
    "Batt.ClearRaw":        ("清空",              "Clear"),

    # protection / alarm bit names
    "Batt.P.CellOv":        ("电芯过压",          "Cell OV"),
    "Batt.P.PackOv":        ("总压过压",          "Pack OV"),
    "Batt.P.Full":          ("充满保护",          "Full"),
    "Batt.P.CellUv":        ("电芯欠压",          "Cell UV"),
    "Batt.P.PackUv":        ("总压欠压",          "Pack UV"),
    "Batt.P.ChargeTemp":    ("充电温度保护",      "Charge temp"),
    "Batt.P.DischargeTemp": ("放电温度保护",      "Discharge temp"),
    "Batt.P.MosOverTemp":   ("MOS 过温",          "MOS over-temp"),
    "Batt.P.HighTemp":      ("高温",              "High temp"),
    "Batt.P.LowTemp":       ("低温",              "Low temp"),
    "Batt.P.ShortCircuit":  ("放电短路",          "Short circuit"),
    "Batt.P.DischargeOc":   ("放电过流",          "Discharge OC"),
    "Batt.P.ChargeOc":      ("充电过流",          "Charge OC"),
    "Batt.P.AmbientHigh":   ("环境高温",          "Ambient high"),
    "Batt.P.AmbientLow":    ("环境低温",          "Ambient low"),
    "Batt.A.CellOverDis":   ("电芯过放",          "Cell over-discharge"),
    "Batt.A.PackOverDis":   ("总压过放",          "Pack over-discharge"),
    "Batt.A.CellOv":        ("电芯过压",          "Cell OV"),
    "Batt.A.PackOv":        ("总压过压",          "Pack OV"),
    "Batt.A.DischargeOc":   ("放电过流",          "Discharge OC"),
    "Batt.A.ChargeOc":      ("充电过流",          "Charge OC"),
    "Batt.A.DischargeOt":   ("放电过温",          "Discharge OT"),
    "Batt.A.ChargeOt":      ("充电过温",          "Charge OT"),
    "Batt.A.SocLow":        ("SOC 低",            "SOC low"),
    "Batt.F.TempFail":      ("温度采集失效",      "Temp sense fail"),
    "Batt.F.VoltFail":      ("电压采集失效",      "Volt sense fail"),
    "Batt.F.DischargeMos":  ("放电 MOS 失效",     "Discharge MOS fail"),
    "Batt.F.ChargeMos":     ("充电 MOS 失效",     "Charge MOS fail"),
    "Batt.F.BalanceWarn":   ("电芯不均衡告警",    "Cell imbalance"),
}

# (label_key, byte_index_in_status_data, bit)
_PROTECT_BITS = [
    ("Batt.P.CellOv", 3, 0), ("Batt.P.PackOv", 3, 1), ("Batt.P.Full", 3, 4),
    ("Batt.P.CellUv", 4, 0), ("Batt.P.PackUv", 4, 1),
    ("Batt.P.ChargeTemp", 5, 0), ("Batt.P.DischargeTemp", 5, 1),
    ("Batt.P.MosOverTemp", 5, 2), ("Batt.P.HighTemp", 5, 4),
    ("Batt.P.LowTemp", 5, 5),
    ("Batt.P.ShortCircuit", 6, 0), ("Batt.P.DischargeOc", 6, 1),
    ("Batt.P.ChargeOc", 6, 2), ("Batt.P.AmbientHigh", 6, 4),
    ("Batt.P.AmbientLow", 6, 5),
]
_ALARM1_BITS = [
    ("Batt.A.CellOverDis", 0), ("Batt.A.PackOverDis", 1), ("Batt.A.CellOv", 2),
    ("Batt.A.PackOv", 3), ("Batt.A.DischargeOc", 4), ("Batt.A.ChargeOc", 5),
    ("Batt.A.DischargeOt", 6), ("Batt.A.ChargeOt", 7),
]
_ALARM2_BITS = [
    ("Batt.P.AmbientHigh", 0), ("Batt.P.AmbientLow", 1),
    ("Batt.A.SocLow", 2), ("Batt.P.MosOverTemp", 3),
]
_FAILURE_BITS = [
    ("Batt.F.TempFail", 0), ("Batt.F.VoltFail", 1), ("Batt.F.DischargeMos", 2),
    ("Batt.F.ChargeMos", 3), ("Batt.F.BalanceWarn", 4),
]


class _ConfigStore:
    PLUGIN_NAME = "battery_monitor"
    DEFAULTS = {
        "addr": 1,
        "auto_poll": True,
        "poll_ms": 250,
        "current_offset": 0,
    }

    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        v = self._ctx.get_setting(f"{self.PLUGIN_NAME}.{key}", default)
        if isinstance(default, bool):
            return bool(v)
        if isinstance(default, int) and isinstance(v, (int, float)):
            return int(v)
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


class BatteryPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)
        self._asm = P.Assembler()
        self._cmd_index = 0
        self._last_rx = 0.0
        self._voltage = None
        self._status = None
        self._soc = None
        self._battery_id = None

        self._static: list = []      # (widget, i18n key) 静态文案
        self._titles: list = []      # (QGroupBox, i18n key)

        self._build_ui()
        self._load_config()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._update_status_label)
        self._refresh_status()

    # ── UI ──
    def _label(self, key: str) -> QLabel:
        lbl = QLabel(_(key))
        self._static.append((lbl, key))
        return lbl

    def _unit(self, key: str, width: int = 34) -> QLabel:
        lbl = QLabel(_(key))
        lbl.setStyleSheet(f"color: {_DIM};")
        lbl.setFixedWidth(width)
        self._static.append((lbl, key))
        return lbl

    def _group(self, key: str) -> QGroupBox:
        box = QGroupBox(_(key))
        self._titles.append((box, key))
        return box

    def _button(self, key: str, slot) -> QPushButton:
        btn = QPushButton(_(key))
        btn.clicked.connect(slot)
        self._static.append((btn, key))
        return btn

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_config())
        root.addWidget(self._build_overview())
        root.addWidget(self._build_cells())
        root.addWidget(self._build_temps_and_state())
        root.addWidget(self._build_protect())
        root.addWidget(self._build_raw())
        root.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_config(self) -> QGroupBox:
        box = self._group("Batt.DevConfig")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)

        g.addWidget(self._label("Batt.Addr"), 0, 0)
        self._addr_spin = QSpinBox()
        self._addr_spin.setRange(P.ADDR_MIN, P.ADDR_MAX)
        self._addr_spin.setValue(P.DEFAULT_ADDR)
        self._addr_spin.valueChanged.connect(self._on_addr_changed)
        g.addWidget(self._addr_spin, 0, 1)

        self._auto_chk = QCheckBox(_("Batt.AutoPoll"))
        self._auto_chk.setChecked(True)
        self._auto_chk.toggled.connect(self._on_auto_changed)
        g.addWidget(self._auto_chk, 0, 2)

        g.addWidget(self._label("Batt.PollInterval"), 0, 3)
        self._poll_spin = QSpinBox()
        self._poll_spin.setRange(100, 5000)
        self._poll_spin.setSingleStep(50)
        self._poll_spin.setValue(250)
        self._poll_spin.valueChanged.connect(self._on_poll_interval_changed)
        g.addWidget(self._poll_spin, 0, 4)
        self._poll_unit = QLabel("ms")
        self._poll_unit.setStyleSheet(f"color: {_DIM};")
        self._poll_unit.setFixedWidth(34)
        g.addWidget(self._poll_unit, 0, 5)

        g.addWidget(self._label("Batt.OffsetRaw"), 1, 0)
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 65535)
        self._offset_spin.setValue(0)
        self._offset_spin.valueChanged.connect(self._on_offset_changed)
        g.addWidget(self._offset_spin, 1, 1)

        self._refresh_btn = self._button("Batt.Refresh", self._on_refresh)
        g.addWidget(self._refresh_btn, 1, 2)

        self._status_label = QLabel(_("Batt.NoData"))
        self._status_label.setStyleSheet(f"color: {_DIM};")
        g.addWidget(self._status_label, 1, 3, 1, 3)
        g.setColumnStretch(6, 1)
        return box

    def _build_overview(self) -> QGroupBox:
        box = self._group("Batt.Overview")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)

        self._ov = {}
        fields = [
            ("soc", "Batt.Soc", "Batt.Unit.Pct"),
            ("pack_v", "Batt.PackVoltage", "Batt.Unit.V"),
            ("current", "Batt.Current", "Batt.Unit.A"),
            ("cycles", "Batt.Cycles", "Batt.Unit.Times"),
            ("max_cell", "Batt.MaxCell", "Batt.Unit.mV"),
            ("min_cell", "Batt.MinCell", "Batt.Unit.mV"),
            ("delta", "Batt.DeltaCell", "Batt.Unit.mV"),
            ("remain", "Batt.RemainCap", "Batt.Unit.Ah"),
            ("design", "Batt.DesignCap", "Batt.Unit.Ah"),
            ("dis_time", "Batt.DischargeTime", "Batt.Unit.Min"),
            ("chg_time", "Batt.ChargeTime", "Batt.Unit.Min"),
        ]
        for i, (key, label_key, unit_key) in enumerate(fields):
            r, c = i // 4, (i % 4) * 3
            g.addWidget(self._label(label_key), r, c)
            val = QLabel(_("Batt.NoData"))
            val.setStyleSheet(f"color: {_OK}; font-weight: 600;")
            g.addWidget(val, r, c + 1)
            g.addWidget(self._unit(unit_key), r, c + 2)
            self._ov[key] = val
        g.setColumnStretch(12, 1)
        return box

    def _build_cells(self) -> QGroupBox:
        box = self._group("Batt.Cells")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self._cell_summary = QLabel(_("Batt.NoData"))
        self._cell_summary.setStyleSheet(f"color: {_DIM};")
        lay.addWidget(self._cell_summary)

        self._cell_table = QTableWidget(0, 4)
        self._cell_table.setHorizontalHeaderLabels(
            [_("Batt.CellNo"), _("Batt.Unit.mV"),
             _("Batt.CellNo"), _("Batt.Unit.mV")])
        self._cell_table.verticalHeader().setVisible(False)
        self._cell_table.setShowGrid(False)
        self._cell_table.setAlternatingRowColors(False)
        self._cell_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cell_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection)
        self._cell_table.setMinimumHeight(245)
        self._cell_table.verticalHeader().setDefaultSectionSize(22)
        for col in range(4):
            self._cell_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._cell_table)
        return box

    def _build_temps_and_state(self) -> QGroupBox:
        box = self._group("Batt.Temps")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)

        self._temp_labels = {}
        rows = [
            ("cell_temps", "Batt.CellTemps", "Batt.Unit.C"),
            ("mos_temp", "Batt.MosTemp", "Batt.Unit.C"),
            ("ambient", "Batt.AmbientTemp", "Batt.Unit.C"),
            ("max_temp", "Batt.MaxTemp", "Batt.Unit.C"),
        ]
        for i, (key, label_key, unit_key) in enumerate(rows):
            r, c = i // 2, (i % 2) * 3
            g.addWidget(self._label(label_key), r, c)
            val = QLabel(_("Batt.NoData"))
            val.setStyleSheet(f"color: {_TEXT}; font-weight: 600;")
            g.addWidget(val, r, c + 1)
            g.addWidget(self._unit(unit_key), r, c + 2)
            self._temp_labels[key] = val

        base = 2
        state_rows = [
            ("flags", "Batt.Flags"),
            ("mos_state", "Batt.MosState"),
            ("failure", "Batt.Failure"),
            ("sw", "Batt.SwVersion"),
            ("hw", "Batt.HwVersion"),
            ("battery_id", "Batt.BatteryId"),
        ]
        for i, (key, label_key) in enumerate(state_rows):
            r = base + i // 2
            c = (i % 2) * 3
            g.addWidget(self._label(label_key), r, c)
            val = QLabel(_("Batt.NoData"))
            val.setStyleSheet(f"color: {_OK}; font-weight: 600;")
            g.addWidget(val, r, c + 1, 1, 2)
            self._temp_labels[key] = val
        g.setColumnStretch(6, 1)
        return box

    def _build_protect(self) -> QGroupBox:
        box = self._group("Batt.Protect")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(2)

        self._bit_labels = []
        entries = list(_PROTECT_BITS) + [
            (k, 8, b) for k, b in _ALARM1_BITS
        ] + [
            (k, 9, b) for k, b in _ALARM2_BITS
        ] + [
            (k, 10, b) for k, b in _FAILURE_BITS
        ]
        per_col = 8
        for i, (key, _byte, _bit) in enumerate(entries):
            r, c = i % per_col, (i // per_col) * 2
            lbl = QLabel(_(key))
            lbl.setStyleSheet(f"color: {_DIM};")
            g.addWidget(lbl, r, c, 1, 2)
            self._bit_labels.append((key, lbl))
        g.setColumnStretch(6, 1)
        return box

    def _build_raw(self) -> QGroupBox:
        box = self._group("Batt.Raw")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.addStretch(1)
        self._clear_raw_btn = self._button(
            "Batt.ClearRaw", lambda: self._raw.clear())
        row.addWidget(self._clear_raw_btn)
        lay.addLayout(row)

        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setMaximumHeight(120)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._raw.setFont(mono)
        lay.addWidget(self._raw)
        return box

    # ── config ──
    def _load_config(self):
        for name, widget, key in (
            ("addr", self._addr_spin, "addr"),
            ("auto", self._auto_chk, "auto_poll"),
            ("poll", self._poll_spin, "poll_ms"),
            ("offset", self._offset_spin, "current_offset"),
        ):
            widget.blockSignals(True)
            if name == "auto":
                widget.setChecked(bool(self._cfg.get(key)))
            else:
                widget.setValue(int(self._cfg.get(key)))
            widget.blockSignals(False)

    def _on_addr_changed(self, value: int):
        self._cfg.set("addr", int(value))
        self._asm.reset()
        self._cmd_index = 0

    def _on_auto_changed(self, checked: bool):
        self._cfg.set("auto_poll", bool(checked))
        self._update_poll_timer()

    def _on_poll_interval_changed(self, value: int):
        self._cfg.set("poll_ms", int(value))
        self._poll_timer.setInterval(int(value))

    def _on_offset_changed(self, value: int):
        self._cfg.set("current_offset", int(value))
        if self._status is not None:
            self._on_status(self._status)

    def _on_refresh(self):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Batt.NotConnected"), 3000)
            return
        self._cmd_index = 0
        self._send_next()

    # ── 发送 ──
    def _send_next(self):
        if not self._ctx.is_connected():
            return
        cmd = P.POLL_COMMANDS[self._cmd_index % len(P.POLL_COMMANDS)]
        self._cmd_index += 1
        addr = int(self._addr_spin.value())
        for frame in P.build_command_frames(addr, cmd):
            self._ctx.send_frame(frame)
        self._raw_append("TX  %s  %s" % (
            P.describe(cmd), P.build_command(addr, cmd).hex(" ").upper()))

    def _on_poll_tick(self):
        if not self._ctx.is_connected():
            self._poll_timer.stop()
            return
        self._send_next()

    def _update_poll_timer(self):
        if self._ctx.is_connected() and self._auto_chk.isChecked():
            self._poll_timer.start(int(self._poll_spin.value()))
        else:
            self._poll_timer.stop()

    def _raw_append(self, text: str):
        self._raw.appendPlainText(text)
        doc = self._raw.document()
        if doc.blockCount() > RAW_MAX_LINES:
            cursor = self._raw.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    # ── 接收 ──
    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        for f in frames:
            if getattr(f, "is_tx", False) or f.is_error:
                continue
            if f.can_id not in P.PACKET_IDS:
                continue
            packet = self._asm.feed(f.can_id, f.data)
            if packet is None:
                continue
            self._handle_packet(packet)

    def _handle_packet(self, packet: bytes):
        reply = P.parse_reply(packet)
        if reply is None:
            self._raw_append("RX  bad packet: %s" % packet.hex(" ").upper())
            return
        self._last_rx = time.monotonic()
        flag = "" if reply.bcc_ok else "  [BCC!]"
        self._raw_append("RX  %s  addr=%d  %s%s" % (
            P.describe(reply.cmd), reply.addr,
            reply.raw.hex(" ").upper(), flag))

        if reply.cmd == P.CMD_VOLTAGE:
            data = P.parse_voltage(reply.data)
            if data is not None:
                self._on_voltage(data)
        elif reply.cmd == P.CMD_STATUS:
            data = P.parse_status(reply.data)
            if data is not None:
                self._on_status(data)
        elif reply.cmd == P.CMD_SOC:
            data = P.parse_soc(reply.data)
            if data is not None:
                self._on_soc(data)
        elif reply.cmd == P.CMD_BATTERY_ID:
            text = P.parse_battery_id(reply.data)
            if text:
                self._battery_id = text
                self._temp_labels["battery_id"].setText(text)
        elif reply.cmd == 0xFF:
            self._raw_append("OK  MOS control acknowledged")
        self._update_status_label()

    # ── 展示 ──
    def _set(self, key: str, text: str):
        self._ov[key].setText(text)

    def _on_voltage(self, data: P.VoltageData):
        self._voltage = data
        cells = data.cells_mv
        if not cells:
            return
        mx, mn = max(cells), min(cells)
        mxi, mni = cells.index(mx) + 1, cells.index(mn) + 1
        self._set("max_cell", str(mx))
        self._set("min_cell", str(mn))
        self._set("delta", str(mx - mn))
        self._cell_summary.setText(_("Batt.CellSummary").format(
            mx=mx, mxi=mxi, mn=mn, mni=mni, d=mx - mn))
        if self._soc is None or self._soc.total_voltage_cv is None:
            self._set("pack_v", "%.2f" % (sum(cells) / 1000.0))

        table = self._cell_table
        half = (len(cells) + 1) // 2
        table.setRowCount(half)
        for i, mv in enumerate(cells):
            row = i if i < half else i - half
            col = 0 if i < half else 2
            no_item = table.item(row, col)
            if no_item is None:
                no_item = QTableWidgetItem()
                no_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, col, no_item)
            val_item = table.item(row, col + 1)
            if val_item is None:
                val_item = QTableWidgetItem()
                val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, col + 1, val_item)
            no_item.setText(str(i + 1))
            val_item.setText(str(mv))
            color = _TEXT
            if mv == mx:
                color = _ERR
            elif mv == mn:
                color = _WARN
            val_item.setForeground(QColor(color))
        # 清除多余单元格（串数减少时）
        for i in range(len(cells), 4 * half):
            row = i if i < half else i - half
            col = 0 if i < half else 2
            for c in (col, col + 1):
                item = table.item(row, c)
                if item is not None:
                    item.setText("")

    def _on_status(self, data: P.StatusData):
        self._status = data
        offset = int(self._offset_spin.value())
        current_ma = data.current_ma(offset)
        self._set("current", "%.2f" % (current_ma / 1000.0))

        temps = ", ".join("%d" % t for t in data.cell_temps) or _("Batt.NoData")
        self._temp_labels["cell_temps"].setText(temps)
        self._temp_labels["mos_temp"].setText(
            _("Batt.NoData") if data.mos_temp is None else "%d" % data.mos_temp)
        self._temp_labels["ambient"].setText(
            _("Batt.NoData") if data.ambient_temp is None else "%d" % data.ambient_temp)
        max_temp = data.max_temp()
        self._temp_labels["max_temp"].setText(
            _("Batt.NoData") if max_temp is None else "%d" % max_temp)

        parts = []
        if data.discharging:
            parts.append(_("Batt.Discharging"))
        if data.charging:
            parts.append(_("Batt.Charging"))
        if not parts:
            parts.append(_("Batt.Idle"))
        if data.key_on:
            parts.append(_("Batt.KeyOn"))
        self._temp_labels["flags"].setText("  ·  ".join(parts))

        mos = []
        if data.mos_status is not None:
            if data.mos_status & 0x02:
                mos.append(_("Batt.MosDischargeOn"))
            if data.mos_status & 0x04:
                mos.append(_("Batt.MosChargeOn"))
        self._temp_labels["mos_state"].setText(
            "  ·  ".join(mos) if mos else _("Batt.NoData"))
        self._temp_labels["failure"].setText(
            _("Batt.NoData") if data.failure is None else "0x%02X" % data.failure)
        self._temp_labels["sw"].setText(
            _("Batt.NoData") if data.sw_version is None else str(data.sw_version))

        active = set()
        for key, byte, bit in _PROTECT_BITS:
            value = [data.over_voltage, data.under_voltage, data.temp_protect,
                     data.other_protect][byte - 3]
            if value & (1 << bit):
                active.add(key)
        if data.alarm1 is not None:
            for key, bit in _ALARM1_BITS:
                if data.alarm1 & (1 << bit):
                    active.add(key)
        if data.alarm2 is not None:
            for key, bit in _ALARM2_BITS:
                if data.alarm2 & (1 << bit):
                    active.add(key)
        if data.failure is not None:
            for key, bit in _FAILURE_BITS:
                if data.failure & (1 << bit):
                    active.add(key)
        for key, lbl in self._bit_labels:
            if key in active:
                lbl.setStyleSheet(f"color: {_ERR}; font-weight: 600;")
            else:
                lbl.setStyleSheet(f"color: {_DIM};")

    def _on_soc(self, data: P.SocData):
        self._soc = data
        if data.soc is not None:
            self._set("soc", str(data.soc))
        if data.total_voltage_v is not None:
            self._set("pack_v", "%.2f" % data.total_voltage_v)
        if data.cycles is not None:
            self._set("cycles", str(data.cycles))
        if data.remain_mah is not None:
            self._set("remain", "%.2f" % (data.remain_mah / 1000.0))
        if data.design_mah is not None:
            self._set("design", "%.2f" % (data.design_mah / 1000.0))
        if data.discharge_min is not None:
            self._set("dis_time", str(data.discharge_min))
        if data.charge_min is not None:
            self._set("chg_time", str(data.charge_min))
        if data.max_cell_mv is not None:
            self._set("max_cell", str(data.max_cell_mv))
        if data.min_cell_mv is not None:
            self._set("min_cell", str(data.min_cell_mv))
        if data.max_cell_mv is not None and data.min_cell_mv is not None:
            self._set("delta", str(data.max_cell_mv - data.min_cell_mv))
        if data.hw_version is not None:
            self._temp_labels["hw"].setText(str(data.hw_version))

    def _update_status_label(self):
        if not self._ctx.is_connected():
            self._status_label.setText(_("Batt.NotConnected"))
            self._status_label.setStyleSheet(f"color: {_DIM};")
            return
        if not self._last_rx:
            self._status_label.setText(_("Batt.Offline"))
            self._status_label.setStyleSheet(f"color: {_WARN};")
            return
        age = time.monotonic() - self._last_rx
        if age <= STALE_S:
            stamp = datetime.now().strftime("%H:%M:%S")
            self._status_label.setText(
                f"{_('Batt.Online')} · {_('Batt.UpdatedAt')} {stamp}")
            self._status_label.setStyleSheet(f"color: {_OK};")
        else:
            self._status_label.setText(_("Batt.Offline"))
            self._status_label.setStyleSheet(f"color: {_WARN};")

    def _refresh_status(self):
        self._update_status_label()

    # ── 生命周期 ──
    def on_activated(self):
        self._stale_timer.start()
        self._update_poll_timer()

    def on_deactivating(self):
        self._poll_timer.stop()
        self._stale_timer.stop()

    def on_connect(self):
        self._asm.reset()
        self._cmd_index = 0
        self._last_rx = 0.0
        self._update_status_label()
        self._stale_timer.start()
        if self._ctx.is_fd_mode():
            self._ctx.status_message(_("Batt.Hint.Bitrate"), 4000)
        elif self._ctx.get_bitrate() != 250_000:
            self._ctx.status_message(_("Batt.Hint.Bitrate"), 4000)
        self._update_poll_timer()

    def on_disconnect(self):
        self._poll_timer.stop()
        self._stale_timer.stop()
        self._asm.reset()
        self._last_rx = 0.0
        self._update_status_label()

    def refresh_language(self):
        for box, key in self._titles:
            box.setTitle(_(key))
        for widget, key in self._static:
            if hasattr(widget, "setText"):
                widget.setText(_(key))
        self._update_status_label()
