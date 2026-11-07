"""G0 双路扭矩传感器读取 UI 面板。

布局：
    ┌ 上报配置 ─────────────────────────────────────────────┐
    │ 采样率 [1000] Hz [设置采样率] [初始化上报] □连接后自动初始化 │
    │                                    [全部开始] [全部停止]  │
    ├───────────────────────────┬───────────────────────────┤
    │ sensor0 · 0x510→0x410/0x411│ sensor1 · 0x520→0x420/0x421│
    │ 校正扭矩 / 原始值 / 软件零点 │ …                         │
    │ 数据格式 / 有效帧数 / 应答   │ …                         │
    │ 状态                       │ …                         │
    │ [开始][停止][硬件标零][软件标零][清除零点] │ …          │
    └───────────────────────────┴───────────────────────────┘

接收主线程派发的批量帧（100ms），按 CAN ID + 数据前缀区分"新格式测量 /
旧格式测量 / 配置应答"，仅更新对应通道，避免无谓重绘。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout,
                                QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                                QPlainTextEdit, QPushButton, QScrollArea,
                                QSpinBox, QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style
from cangui.plugin_ui import DisclosureSection, FlowLayout

from . import protocol as P
from .scope import DEFAULT_WINDOW_S, WINDOW_CHOICES, TorqueScope
from .setid import SetIdSignals, SetIdTask

logger = logging.getLogger("plugin.torque_sensor")

# 颜色（复用 style.py 常量，不硬编码 hex）

# 命令应答超时（秒）：配置写入应答通常很快，超过即视为超时
_CMD_TIMEOUT_S = 1.5
# 硬件标零等待应答窗口（秒）：协议文档为 32 次 × 20ms
_HW_ZERO_TIMEOUT_MS = 700

# ── i18n keys（plugin.init() 注册）──
_I18N_KEYS = {
    "Torque.Title":             ("扭矩传感器",              "Torque Sensor"),
    "Torque.Config":            ("上报配置",                "Reporting Config"),
    "Torque.SampleRate":        ("采样率",                  "Sample Rate"),
    "Torque.SetSampleRate":     ("设置采样率",              "Set Sample Rate"),
    "Torque.InitAll":           ("初始化上报",              "Initialize Reporting"),
    "Torque.AutoInit":          ("连接后自动初始化",        "Auto-init on connect"),
    "Torque.StartAll":          ("全部开始",                "Start All"),
    "Torque.StopAll":           ("全部停止",                "Stop All"),

    "Torque.Raw":               ("原始扭矩",                "Raw Torque"),
    "Torque.Offset":            ("软件零点",                "SW Offset"),
    "Torque.Corrected":         ("校正扭矩",                "Corrected Torque"),
    "Torque.Format":            ("数据格式",                "Frame Format"),
    "Torque.Frames":            ("有效帧数（无效）",        "Valid (invalid)"),
    "Torque.Ack":               ("应答",                    "Ack"),
    "Torque.Status":            ("状态",                    "Status"),

    "Torque.Fmt.New":           ("新格式",                  "New"),
    "Torque.Fmt.Old":           ("旧格式",                  "Old"),
    "Torque.Fmt.None":          ("未知",                    "Unknown"),

    "Torque.Start":             ("开始",                    "Start"),
    "Torque.Stop":              ("停止",                    "Stop"),
    "Torque.HwZero":            ("硬件标零",                "HW Zero"),
    "Torque.SwZero":            ("软件标零",                "SW Zero"),
    "Torque.ClearOffset":       ("清除零点",                "Clear Offset"),

    "Torque.NoData":            ("—",                       "—"),
    "Torque.NotConnected":      ("CAN 未连接，请先在主界面连接设备",
                                 "CAN not connected. Connect a device first."),
    "Torque.Offline":           ("离线（无数据）",          "Offline (no data)"),
    "Torque.Waiting":           ("等待数据…",              "Waiting for data…"),
    "Torque.UpdatedAt":         ("更新于",                  "Updated at"),

    "Torque.Reporting.On":      ("上报中",                  "Reporting"),
    "Torque.Reporting.Off":     ("已停止",                  "Stopped"),
    "Torque.Reporting.Pending": ("等待应答…",              "Waiting for ack…"),
    "Torque.Reporting.Unknown": ("未初始化",                "Not initialized"),
    "Torque.Status.Disconnected": ("未连接",                "Not Connected"),

    "Torque.Ack.SampleRate":    ("采样率",                  "Sample rate"),
    "Torque.Ack.ReportMode":    ("上报模式",                "Report mode"),
    "Torque.Ack.HwZero":        ("硬件标零",                "HW zero"),
    "Torque.Ack.Timeout":       ("应答超时",                "Ack timeout"),

    "Torque.SwZeroFailed":      ("软件标零失败：该通道暂无有效数据",
                                 "SW zero failed: no valid data on this channel"),
    "Torque.SwZeroDone":        ("软件标零完成",            "SW zero applied"),
    "Torque.ClearOffsetDone":   ("已清除软件零点",          "SW offset cleared"),
    "Torque.SampleRateSet":     ("已发送采样率设置",        "Sample-rate command sent"),
    "Torque.HwZeroDone":        ("硬件标零完成",            "Hardware zero done"),
    "Torque.HwZeroTimeout":     ("硬件标零超时（未收到应答）",
                                 "Hardware zero timeout (no ack)"),

    "Torque.Unit.Nm":           ("N·m",                    "N·m"),
    "Torque.Unit.Hz":           ("Hz",                     "Hz"),

    "Torque.Hint.Bitrate":      ("提示：该扭矩传感器为 Classic CAN 1 Mbit/s，请确认波特率",
                                 "Hint: sensor uses Classic CAN @ 1 Mbit/s; check bitrate"),
    "Torque.Hint.Fd":           ("提示：该扭矩传感器为 Classic CAN，请关闭 CAN FD",
                                 "Hint: sensor is Classic CAN; disable CAN FD"),

    # ── 扭矩波形 ──
    "Torque.Scope.Title":       ("扭矩波形",                "Torque Waveform"),
    "Torque.Scope.Window":      ("时间窗",                  "Time Window"),
    "Torque.Scope.Pause":       ("暂停",                    "Pause"),
    "Torque.Scope.Resume":      ("继续",                    "Resume"),
    "Torque.Scope.Clear":       ("清除波形",                "Clear"),
    "Torque.Scope.NoData":      ("无数据",                  "No data"),

    # ── 站号扫描 / 设置 ID ──
    "Torque.SetId.Title":       ("传感器 ID 设置",          "Sensor ID Settings"),
    "Torque.SetId.Warn":        ("仅连接一只传感器并先停止主动上报。请求 = 0x500 + ID×0x10，"
                                 "响应 = 0x400 + ID×0x10，站号范围 1~47。",
                                 "Connect only one sensor and stop active reporting first. "
                                 "Request = 0x500 + ID×0x10, response = 0x400 + ID×0x10, station 1..47."),
    "Torque.SetId.Current":     ("当前 ID",                 "Current ID"),
    "Torque.SetId.Target":      ("目标 ID",                 "Target ID"),
    "Torque.SetId.Scan":        ("扫描",                    "Scan"),
    "Torque.SetId.Write":       ("设置 ID",                 "Set ID"),
    "Torque.SetId.Idle":        ("空闲",                    "Idle"),
    "Torque.SetId.Running":     ("运行中…",                "Running…"),
    "Torque.SetId.Scanning":    ("扫描中 {n}/{total}…",    "Scanning {n}/{total}…"),
    "Torque.SetId.Station":     ("{station} (0x{station:02X}) · 请求 0x{rid:03X} / 响应 0x{resp:03X}",
                                 "{station} (0x{station:02X}) · req 0x{rid:03X} / resp 0x{resp:03X}"),
    "Torque.SetId.ScanOk":      ("扫描完成，当前 ID={station}",
                                 "Scan complete, current ID={station}"),
    "Torque.SetId.ScanFail":    ("扫描不满足改号条件：响应站号数={count}（或多回复）。"
                                 "仅连接一只传感器并停止上报后重试。",
                                 "Scan rejected: responding stations={count} (or multi-reply). "
                                 "Connect one sensor, stop reporting, then retry."),
    "Torque.SetId.WriteOk":     ("已设置 ID={target}（收到写成功应答）",
                                 "ID set to {target} (write ack received)"),
    "Torque.SetId.WriteTimeout": ("改号应答超时；地址可能已改变，请重新扫描确认，不要盲目重发",
                                  "Set-ID ack timeout; the ID may already have changed — "
                                  "rescan to confirm and do not blindly resend"),
    "Torque.SetId.WriteError":  ("收到非法写应答",          "Invalid write ack"),
    "Torque.SetId.BadTarget":   ("目标 ID 无效（范围 1~47）",
                                 "Invalid target ID (range 1..47)"),
    "Torque.SetId.Cancelled":   ("已取消",                  "Cancelled"),
    "Torque.SetId.Error":       ("操作失败",                "Operation failed"),
    "Torque.SetId.Busy":        ("ID 设置进行中，请等待完成后再关闭",
                                 "Set-ID in progress; wait for it to finish before closing"),
    "Torque.SetId.Confirm":     ("确认将传感器 ID 改为 {target}？\n\n"
                                 "请确保总线上只连接一只传感器且另一只已断开；"
                                 "改号后原地址不再响应。",
                                 "Set sensor ID to {target}?\n\n"
                                 "Ensure only one sensor is connected and the other is "
                                 "disconnected; the old address will stop responding."),
    "Torque.SetId.Log.Start":       ("开始扫描…",           "Starting scan…"),
    "Torque.SetId.Log.StartWrite":  ("开始设置 ID={target}…", "Setting ID={target}…"),
    "Torque.SetId.Log.Stop":        ("扫描前已向站号 1、2 发送停止上报",
                                     "Sent stop-report to stations 1, 2 before scan"),
    "Torque.SetId.Log.ScanStart":   ("扫描站号 1~{max}…",   "Scanning stations 1..{max}…"),
    "Torque.SetId.Log.ScanFound":   ("发现站号 {station}",  "Found station {station}"),
    "Torque.SetId.Log.Found":       ("站号 {station} 匹配回复 {replies}",
                                     "Station {station}: {replies} matching repl(ies)"),
    "Torque.SetId.Log.ScanReject":  ("扫描不满足改号条件：响应站号数={count}，多回复={multi}",
                                     "Scan rejected: stations={count}, multi-reply={multi}"),
    "Torque.SetId.Log.Writing":     ("将站号 {current} 改为 {target}…",
                                     "Writing station {current} → {target}…"),
    "Torque.SetId.Log.WriteOk":     ("写入成功：ID={target}", "Write ok: ID={target}"),
    "Torque.SetId.Log.Error":       ("异常：{msg}",         "Error: {msg}"),
}


class _ConfigStore:
    PLUGIN_NAME = "torque_sensor"
    DEFAULTS = {
        "sample_rate": int(P.DEFAULT_SAMPLE_RATE),
        "auto_init": True,
        "offset0": 0.0,
        "offset1": 0.0,
        "setid_target": 1,
        "scope_window": float(DEFAULT_WINDOW_S),
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
        if isinstance(default, float) and isinstance(v, (int, float)):
            return float(v)
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


class TorqueSensorPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)
        self._st = [P.ChannelState() for _ in range(P.NUM_CHANNELS)]
        for i in range(P.NUM_CHANNELS):
            self._st[i].offset = float(self._cfg.get(f"offset{i}"))

        self._static: list = []        # (QLabel, i18n key) 静态文本，语言切换时刷新
        self._titles: list = []        # (QGroupBox, i18n key)
        self._chan: list = []          # 每通道控件字典
        self._stale_threshold = 2.0    # 秒

        # 序列状态（避免使用 QTimer.singleShot 回调已销毁 widget）
        self._init_stage = None
        self._hz_stage = None
        self._hz_target = None
        self._hz_restore: list = []

        # 站号扫描 / 改号状态
        self._setid_busy = False
        self._setid_task = None
        self._setid_signals = None
        self._setid_current = None
        self._setid_restore: list = []
        self._setid_status_key = "Torque.SetId.Idle"
        self._setid_status_params = None
        self._setid_status_color = style.FG_DIM

        self._build_ui()
        self._load_config_to_ui()

        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._update_status)

        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.timeout.connect(self._init_step)

        self._hz_timer = QTimer(self)
        self._hz_timer.setSingleShot(True)
        self._hz_timer.timeout.connect(self._hz_step)

        self._update_status()

    # ── UI 构建 ──
    def _label(self, key: str) -> QLabel:
        lbl = QLabel(_(key))
        self._static.append((lbl, key))
        return lbl

    def _btn(self, key: str, slot, primary: bool = False) -> QPushButton:
        btn = QPushButton(_(key))
        if primary:
            btn.setObjectName("primaryBtn")
        btn.clicked.connect(slot)
        self._static.append((btn, key))
        return btn

    def _group(self, key: str) -> QGroupBox:
        box = QGroupBox(_(key))
        self._titles.append((box, key))
        return box

    def _build_ui(self):
        # 内容可滚动：波形 + 通道 + 设置ID 在小窗口下不至于被裁剪
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_config_box())

        chan_row = QHBoxLayout()
        chan_row.setSpacing(8)
        for i in range(P.NUM_CHANNELS):
            chan_row.addWidget(self._build_channel_box(i), 1)
        root.addLayout(chan_row)

        root.addWidget(self._build_scope_box(), 1)
        root.addWidget(self._build_setid_box())

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_config_box(self) -> QGroupBox:
        box = self._group("Torque.Config")
        lay = FlowLayout(box)

        lay.addWidget(self._label("Torque.SampleRate"))
        self._rate_spin = QSpinBox()
        self._rate_spin.setRange(1, 20000)
        self._rate_spin.setSingleStep(100)
        self._rate_spin.setValue(int(P.DEFAULT_SAMPLE_RATE))
        self._rate_spin.setSuffix(" " + _("Torque.Unit.Hz"))
        self._rate_spin.valueChanged.connect(self._on_rate_changed)
        lay.addWidget(self._rate_spin)

        lay.addWidget(self._btn("Torque.SetSampleRate", self._on_set_rate))
        lay.addWidget(self._btn("Torque.InitAll", self._on_init_all, primary=True))

        self._auto_init_chk = QCheckBox(_("Torque.AutoInit"))
        self._auto_init_chk.toggled.connect(self._on_auto_init_changed)
        self._static.append((self._auto_init_chk, "Torque.AutoInit"))
        lay.addWidget(self._auto_init_chk)

        lay.addWidget(self._btn("Torque.StartAll", self._on_start_all))
        lay.addWidget(self._btn("Torque.StopAll", self._on_stop_all))
        return box

    def _build_channel_box(self, i: int) -> QGroupBox:
        ch = P.CHANNELS[i]
        box = QGroupBox(
            f"{ch['name']}  ·  0x{ch['request_id']:03X} → "
            f"0x{ch['new_id']:03X} / 0x{ch['old_id']:03X}")
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        unit = self._label("Torque.Unit.Nm")

        big = QLabel(_("Torque.NoData"))
        f = QFont()
        f.setPointSize(f.pointSize() + 5)
        f.setBold(True)
        big.setFont(f)
        style.set_text_color(big, style.LOAD_LOW)

        raw = QLabel(_("Torque.NoData"))
        off = QLabel("+0.000")
        for w in (raw, off):
            style.set_text_color(w, style.FG_DIM)

        fmt = QLabel(_("Torque.Fmt.None"))
        frames = QLabel("0 (0)")
        ack = QLabel(_("Torque.NoData"))
        style.set_text_color(ack, style.FG_DIM)
        status = QLabel(_("Torque.Reporting.Unknown"))
        style.set_text_color(status, style.FG_DIM)

        grid.addWidget(self._label("Torque.Corrected"), 0, 0)
        grid.addWidget(big, 0, 1, 1, 4)
        grid.addWidget(unit, 0, 5)
        grid.addWidget(self._label("Torque.Raw"), 1, 0)
        grid.addWidget(raw, 1, 1, 1, 2)
        grid.addWidget(self._label("Torque.Offset"), 1, 3)
        grid.addWidget(off, 1, 4, 1, 2)
        grid.addWidget(self._label("Torque.Format"), 2, 0)
        grid.addWidget(fmt, 2, 1, 1, 2)
        grid.addWidget(self._label("Torque.Frames"), 2, 3)
        grid.addWidget(frames, 2, 4, 1, 2)
        grid.addWidget(self._label("Torque.Ack"), 3, 0)
        grid.addWidget(ack, 3, 1, 1, 2)
        grid.addWidget(self._label("Torque.Status"), 3, 3)
        grid.addWidget(status, 3, 4, 1, 2)

        btn_row = FlowLayout()
        btn_row.addWidget(self._btn("Torque.Start", lambda: self._on_start(i)))
        btn_row.addWidget(self._btn("Torque.Stop", lambda: self._on_stop(i)))
        btn_row.addWidget(self._btn("Torque.HwZero", lambda: self._on_hw_zero(i)))
        btn_row.addWidget(self._btn("Torque.SwZero", lambda: self._on_sw_zero(i)))
        btn_row.addWidget(self._btn("Torque.ClearOffset",
                                    lambda: self._on_clear_offset(i)))
        grid.addLayout(btn_row, 4, 0, 1, 6)

        self._chan.append({"big": big, "raw": raw, "off": off, "fmt": fmt,
                           "frames": frames, "ack": ack, "status": status,
                           "unit": unit})
        return box

    def _load_config_to_ui(self):
        self._rate_spin.blockSignals(True)
        self._rate_spin.setValue(int(self._cfg.get("sample_rate")))
        self._rate_spin.blockSignals(False)

        self._auto_init_chk.blockSignals(True)
        self._auto_init_chk.setChecked(bool(self._cfg.get("auto_init")))
        self._auto_init_chk.blockSignals(False)

    # ── 扭矩波形 ──
    def _build_scope_box(self) -> QGroupBox:
        box = self._group("Torque.Scope.Title")
        lay = QVBoxLayout(box)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(self._label("Torque.Scope.Window"))
        self._scope_window_combo = QComboBox()
        for seconds in WINDOW_CHOICES:
            self._scope_window_combo.addItem(f"{int(seconds)} s", float(seconds))
        self._scope_window_combo.currentIndexChanged.connect(
            self._on_scope_window_changed)
        row.addWidget(self._scope_window_combo)
        row.addSpacing(12)

        self._scope_pause_btn = QPushButton(_("Torque.Scope.Pause"))
        self._scope_pause_btn.setCheckable(True)
        self._scope_pause_btn.toggled.connect(self._on_scope_pause_toggled)
        row.addWidget(self._scope_pause_btn)
        row.addWidget(self._btn("Torque.Scope.Clear", self._on_scope_clear))
        row.addStretch(1)
        lay.addLayout(row)

        self._scope = TorqueScope(
            names=[ch["name"] for ch in P.CHANNELS],
            colors=[style.FG_ACCENT, style.LOAD_MID])
        self._scope.set_no_data_text(_("Torque.Scope.NoData"))
        for i, st in enumerate(self._st):
            self._scope.set_offset(i, st.offset)

        win = float(self._cfg.get("scope_window"))
        idx = self._scope_window_combo.findData(win)
        if idx < 0:
            idx = self._scope_window_combo.findData(DEFAULT_WINDOW_S)
        self._scope_window_combo.blockSignals(True)
        self._scope_window_combo.setCurrentIndex(max(0, idx))
        self._scope_window_combo.blockSignals(False)
        self._scope.set_window(float(self._scope_window_combo.currentData()))

        lay.addWidget(self._scope, 1)
        return box

    def _on_scope_window_changed(self, _index: int):
        win = float(self._scope_window_combo.currentData())
        self._cfg.set("scope_window", win)
        self._scope.set_window(win)

    def _on_scope_pause_toggled(self, checked: bool):
        self._scope.set_paused(bool(checked))
        self._update_scope_pause_text()

    def _update_scope_pause_text(self):
        self._scope_pause_btn.setText(
            _("Torque.Scope.Resume") if self._scope.is_paused()
            else _("Torque.Scope.Pause"))

    def _on_scope_clear(self):
        self._scope.clear()

    # ── 站号扫描 / 设置 ID ──
    def _build_setid_box(self) -> DisclosureSection:
        box = DisclosureSection(_("Torque.SetId.Title"))
        self._titles.append((box, "Torque.SetId.Title"))
        lay = QVBoxLayout(box.body)
        lay.setSpacing(4)

        info = QLabel(_("Torque.SetId.Warn"))
        info.setWordWrap(True)
        style.set_text_color(info, style.FG_DIM)
        self._static.append((info, "Torque.SetId.Warn"))
        lay.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(self._label("Torque.SetId.Current"))
        self._setid_current_lbl = QLabel(_("Torque.NoData"))
        style.set_text_color(self._setid_current_lbl, style.FG_TEXT, 'font-weight: 600;')
        row.addWidget(self._setid_current_lbl)
        row.addStretch(1)
        self._scan_btn = self._btn("Torque.SetId.Scan", self._on_setid_scan)
        row.addWidget(self._scan_btn)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(self._label("Torque.SetId.Target"))
        self._setid_target_spin = QSpinBox()
        self._setid_target_spin.setRange(1, P.MAX_SENSOR_ID)
        self._setid_target_spin.setValue(int(self._cfg.get("setid_target")))
        self._setid_target_spin.valueChanged.connect(self._on_setid_target_changed)
        row2.addWidget(self._setid_target_spin)
        self._write_btn = self._btn("Torque.SetId.Write", self._on_setid_write,
                                    primary=True)
        row2.addWidget(self._write_btn)
        row2.addStretch(1)
        self._setid_status = QLabel(_("Torque.SetId.Idle"))
        style.set_text_color(self._setid_status, style.FG_DIM)
        row2.addWidget(self._setid_status)
        lay.addLayout(row2)

        self._setid_log = QPlainTextEdit()
        self._setid_log.setReadOnly(True)
        self._setid_log.setMaximumHeight(96)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._setid_log.setFont(mono)
        lay.addWidget(self._setid_log)
        return box

    def is_busy(self) -> bool:
        return self._setid_busy

    def _on_setid_target_changed(self, value: int):
        self._cfg.set("setid_target", int(value))

    def _set_setid_status(self, key: str, color: str, params=None):
        self._setid_status_key = key
        self._setid_status_params = params
        self._setid_status_color = color
        self._render_setid_status()

    def _render_setid_status(self):
        text = _(self._setid_status_key)
        if self._setid_status_params:
            try:
                text = text.format(**self._setid_status_params)
            except Exception:
                pass
        self._setid_status.setText(text)
        style.set_text_color(self._setid_status, self._setid_status_color)

    def _render_setid_current(self):
        if self._setid_current is None:
            self._setid_current_lbl.setText(_("Torque.NoData"))
            return
        st = int(self._setid_current)
        self._setid_current_lbl.setText(_("Torque.SetId.Station").format(
            station=st, rid=P.station_request_id(st),
            resp=P.station_response_id(st)))

    def _append_setid_log(self, level: str, text: str):
        prefix = {"warn": "! ", "error": "x "}.get(level, "")
        self._setid_log.appendPlainText(f"{prefix}{text}")

    def _setid_buttons_enabled(self, enabled: bool):
        self._scan_btn.setEnabled(enabled)
        self._write_btn.setEnabled(enabled)
        self._setid_target_spin.setEnabled(enabled)

    def _on_setid_scan(self):
        self._start_setid(target=None)

    def _on_setid_write(self):
        if self._setid_busy:
            return
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Torque.NotConnected"), 3000)
            return
        target = int(self._setid_target_spin.value())
        if not P.station_valid(target):
            self._set_setid_status("Torque.SetId.BadTarget", style.LOAD_HIGH)
            return
        ret = QMessageBox.warning(
            self, _("Torque.SetId.Title"),
            _("Torque.SetId.Confirm").format(target=target),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._start_setid(target=target)

    def _start_setid(self, target):
        if self._setid_busy:
            return
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Torque.NotConnected"), 3000)
            return
        self._setid_busy = True
        self._setid_buttons_enabled(False)
        self._set_setid_status("Torque.SetId.Running", style.LOAD_MID)
        # 记录改号前正在上报的通道，操作结束后恢复
        self._setid_restore = [i for i in range(P.NUM_CHANNELS)
                               if self._st[i].reporting in ("on", "pending_on")]
        if target is None:
            self._append_setid_log("info", _("Torque.SetId.Log.Start"))
            self._append_setid_log("info", _("Torque.SetId.Log.Stop"))
        else:
            self._append_setid_log(
                "info", _("Torque.SetId.Log.StartWrite").format(target=target))

        self._setid_signals = SetIdSignals()
        self._setid_signals.progress.connect(self._on_setid_progress)
        self._setid_signals.found.connect(self._on_setid_found)
        self._setid_signals.log.connect(self._on_setid_log)
        self._setid_signals.finished.connect(self._on_setid_finished)
        self._setid_task = SetIdTask(
            signals=self._setid_signals, target=target,
            stop_stations=tuple(ch["station"] for ch in P.CHANNELS))
        try:
            self._ctx.start_upgrade(self._setid_task)
        except Exception as exc:
            self._setid_busy = False
            self._setid_buttons_enabled(True)
            self._set_setid_status("Torque.SetId.Error", style.LOAD_HIGH)
            logger.warning("启动扫描/改号任务失败: %s", exc)

    def _on_setid_progress(self, scanned: int, total: int):
        self._set_setid_status("Torque.SetId.Scanning", style.LOAD_MID,
                               {"n": scanned, "total": total})

    def _on_setid_found(self, station: int, replies: int):
        self._append_setid_log("info", _("Torque.SetId.Log.Found").format(
            station=station, replies=replies))

    def _on_setid_log(self, level: str, key: str, params):
        text = _(key)
        if params:
            try:
                text = text.format(**params)
            except Exception:
                pass
        self._append_setid_log(level, text)

    def _on_setid_finished(self, ok: bool, code: str):
        self._setid_busy = False
        self._setid_buttons_enabled(True)
        res = self._setid_task.result if self._setid_task is not None else None

        # 恢复操作前正在上报的通道（扫描前已发送停止上报降噪）
        if self._ctx.is_connected():
            for i in self._setid_restore:
                self._ctx.send_frame(P.build_start_report(i))
                self._mark(i, "start")
        self._setid_restore = []

        if code == "scan_only" and res is not None:
            self._setid_current = res.current
            self._render_setid_current()
            self._set_setid_status("Torque.SetId.ScanOk", style.LOAD_LOW,
                                   {"station": res.current})
        elif code == "write_ok" and res is not None:
            self._setid_current = res.target
            self._render_setid_current()
            self._set_setid_status("Torque.SetId.WriteOk", style.LOAD_LOW,
                                   {"target": res.target})
            self._ctx.status_message(
                _("Torque.SetId.WriteOk").format(target=res.target), 5000)
        elif code == "scan_failed":
            count = len(res.found_stations) if res is not None else 0
            self._set_setid_status("Torque.SetId.ScanFail", style.LOAD_HIGH,
                                   {"count": count})
        elif code == "bad_target":
            self._set_setid_status("Torque.SetId.BadTarget", style.LOAD_HIGH)
        elif code == "write_timeout":
            self._set_setid_status("Torque.SetId.WriteTimeout", style.LOAD_HIGH)
            self._append_setid_log("warn", _("Torque.SetId.WriteTimeout"))
        elif code == "write_error":
            self._set_setid_status("Torque.SetId.WriteError", style.LOAD_HIGH)
        elif code == "cancelled":
            self._set_setid_status("Torque.SetId.Cancelled", style.LOAD_MID)
        else:
            self._set_setid_status("Torque.SetId.Error", style.LOAD_HIGH)

    # ── 配置事件 ──
    def _on_rate_changed(self, value: int):
        self._cfg.set("sample_rate", int(value))

    def _on_auto_init_changed(self, checked: bool):
        self._cfg.set("auto_init", bool(checked))

    # ── 发送辅助 ──
    def _send(self, frame) -> bool:
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Torque.NotConnected"), 3000)
            return False
        self._ctx.send_frame(frame)
        return True

    def _mark(self, i: int, cmd: str):
        st = self._st[i]
        st.pending_cmd = cmd
        st.pending_since = time.monotonic()
        if cmd == "start":
            st.reporting = "pending_on"
        elif cmd == "stop":
            st.reporting = "pending_off"

    # ── 命令：开始 / 停止 / 采样率 ──
    def _on_start(self, i: int):
        if self._send(P.build_start_report(i)):
            self._mark(i, "start")
            self._update_status()

    def _on_stop(self, i: int):
        if self._send(P.build_stop_report(i)):
            self._mark(i, "stop")
            self._update_status()

    def _on_start_all(self):
        sent = False
        for i in range(P.NUM_CHANNELS):
            if self._send(P.build_start_report(i)):
                self._mark(i, "start")
                sent = True
        if sent:
            self._update_status()

    def _on_stop_all(self):
        sent = False
        for i in range(P.NUM_CHANNELS):
            if self._send(P.build_stop_report(i)):
                self._mark(i, "stop")
                sent = True
        if sent:
            self._update_status()

    def _on_set_rate(self):
        rate = float(self._rate_spin.value())
        sent = False
        for i in range(P.NUM_CHANNELS):
            if self._send(P.build_sample_rate(i, rate)):
                self._mark(i, "sample_rate")
                sent = True
        if sent:
            self._ctx.status_message(_("Torque.SampleRateSet"), 3000)
            self._update_status()

    # ── 初始化序列：停止 → 设置采样率 → 开始 ──
    def _on_init_all(self):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Torque.NotConnected"), 3000)
            return
        self._init_stage = 0
        self._init_step()

    def _init_step(self):
        if not self._ctx.is_connected():
            self._init_stage = None
            return
        stage = self._init_stage
        if stage == 0:
            for i in range(P.NUM_CHANNELS):
                if self._ctx.is_connected():
                    self._ctx.send_frame(P.build_stop_report(i))
                    self._mark(i, "stop")
            self._init_stage = 1
            self._init_timer.start(30)
        elif stage == 1:
            rate = float(self._rate_spin.value())
            for i in range(P.NUM_CHANNELS):
                if self._ctx.is_connected():
                    self._ctx.send_frame(P.build_sample_rate(i, rate))
                    self._mark(i, "sample_rate")
            self._init_stage = 2
            self._init_timer.start(30)
        elif stage == 2:
            for i in range(P.NUM_CHANNELS):
                if self._ctx.is_connected():
                    self._ctx.send_frame(P.build_start_report(i))
                    self._mark(i, "start")
            self._init_stage = None
        self._update_status()

    # ── 标零 ──
    def _on_sw_zero(self, i: int):
        st = self._st[i]
        if st.mz_raw is None:
            self._ctx.status_message(_("Torque.SwZeroFailed"), 3000)
            return
        self._set_offset(i, -st.mz_raw)
        self._ctx.status_message(_("Torque.SwZeroDone"), 3000)
        self._update_status()

    def _on_clear_offset(self, i: int):
        self._set_offset(i, 0.0)
        self._ctx.status_message(_("Torque.ClearOffsetDone"), 3000)
        self._update_status()

    def _set_offset(self, i: int, value: float):
        self._st[i].offset = float(value)
        self._cfg.set(f"offset{i}", float(value))
        self._scope.set_offset(i, float(value))
        self._update_channel(i)

    def _on_hw_zero(self, i: int):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Torque.NotConnected"), 3000)
            return
        # 记录需要恢复上报的通道（协议 §7.1）
        self._hz_target = i
        self._hz_restore = [k for k in range(P.NUM_CHANNELS)
                            if self._st[k].reporting in ("on", "pending_on")]
        self._hz_stage = 0
        self._hz_step()

    def _hz_step(self):
        if not self._ctx.is_connected():
            self._hz_stage = None
            self._hz_restore = []
            return
        stage = self._hz_stage
        if stage == 0:
            for k in self._hz_restore:
                self._ctx.send_frame(P.build_stop_report(k))
                self._mark(k, "stop")
            self._hz_stage = 1
            self._hz_timer.start(60)
        elif stage == 1:
            self._ctx.send_frame(P.build_hw_zero(self._hz_target))
            self._hz_stage = 2
            self._hz_timer.start(_HW_ZERO_TIMEOUT_MS)
        elif stage == 2:
            self._finish_hw_zero(False)
        self._update_status()

    def _finish_hw_zero(self, ok: bool):
        if self._hz_stage is None:
            return
        self._hz_timer.stop()
        target = self._hz_target
        restore = self._hz_restore
        self._hz_stage = None
        self._hz_target = None
        self._hz_restore = []

        if ok and target is not None:
            # 硬件标零成功后清除该路软件零点（协议 §7.1）
            self._set_offset(target, 0.0)
            self._ctx.status_message(_("Torque.HwZeroDone"), 3000)
        else:
            self._ctx.status_message(_("Torque.HwZeroTimeout"), 3000)

        for k in restore:
            if self._ctx.is_connected():
                self._ctx.send_frame(P.build_start_report(k))
                self._mark(k, "start")
        self._update_status()

    # ── 帧处理 ──
    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        touched = set()
        for f in frames:
            if getattr(f, "is_tx", False) or f.is_error:
                continue
            res = P.classify(f.can_id, f.data)
            if res is None:
                continue
            st = self._st[res.channel]
            if res.kind == "measure":
                st.mz_raw = res.value
                st.fmt = res.fmt
                st.frames += 1
                st.last_rx = time.monotonic()
                st.reporting = "on"
                if st.pending_cmd == "start":
                    st.pending_cmd = None
                self._scope.add_sample(res.channel,
                                       getattr(f, "timestamp", 0.0), res.value)
            elif res.kind == "ack":
                self._handle_ack(res.channel, res.ack)
            else:
                st.invalid += 1
            touched.add(res.channel)
        if touched:
            for i in touched:
                self._update_channel(i)
            self._update_status()

    def _handle_ack(self, i: int, name: str):
        st = self._st[i]
        st.last_ack = name
        if name == P.ACK_NAME_HW_ZERO:
            if self._hz_stage == 2 and self._hz_target == i:
                self._finish_hw_zero(True)
            return
        if st.pending_cmd == "sample_rate" and name == P.ACK_NAME_SAMPLE_RATE:
            st.pending_cmd = None
            return
        if st.pending_cmd == "start" and name == P.ACK_NAME_REPORT_MODE:
            st.reporting = "on"
            st.pending_cmd = None
            return
        if st.pending_cmd == "stop" and name == P.ACK_NAME_REPORT_MODE:
            st.reporting = "off"
            st.pending_cmd = None

    # ── 显示刷新 ──
    def _fmt_text(self, fmt) -> str:
        if fmt == P.FMT_NEW:
            return _("Torque.Fmt.New")
        if fmt == P.FMT_OLD:
            return _("Torque.Fmt.Old")
        return _("Torque.Fmt.None")

    def _ack_text(self, ack) -> str:
        if ack == "timeout":
            return _("Torque.Ack.Timeout")
        if ack == P.ACK_NAME_SAMPLE_RATE:
            return _("Torque.Ack.SampleRate")
        if ack == P.ACK_NAME_REPORT_MODE:
            return _("Torque.Ack.ReportMode")
        if ack == P.ACK_NAME_HW_ZERO:
            return _("Torque.Ack.HwZero")
        return _("Torque.NoData")

    def _status_text(self, i: int):
        st = self._st[i]
        if not self._ctx.is_connected():
            return _("Torque.Status.Disconnected"), style.FG_DIM
        if st.pending_cmd is not None:
            return _("Torque.Reporting.Pending"), style.LOAD_MID
        if st.reporting == "on":
            if st.last_rx:
                if time.monotonic() - st.last_rx <= self._stale_threshold:
                    t = datetime.now().strftime("%H:%M:%S")
                    return (f"{_('Torque.Reporting.On')} · "
                            f"{_('Torque.UpdatedAt')} {t}", style.LOAD_LOW)
                return _("Torque.Offline"), style.LOAD_MID
            return _("Torque.Waiting"), style.FG_DIM
        if st.reporting == "off":
            return _("Torque.Reporting.Off"), style.FG_DIM
        if st.last_rx:
            return _("Torque.Offline"), style.LOAD_MID
        return _("Torque.Reporting.Unknown"), style.FG_DIM

    def _update_channel(self, i: int):
        if i >= len(self._chan):
            return
        w = self._chan[i]
        st = self._st[i]
        corr = st.corrected()
        w["big"].setText(f"{corr:+.3f}" if corr is not None else _("Torque.NoData"))
        w["raw"].setText(f"{st.mz_raw:+.3f}" if st.mz_raw is not None else _("Torque.NoData"))
        w["off"].setText(f"{st.offset:+.3f}")
        w["fmt"].setText(self._fmt_text(st.fmt))
        w["frames"].setText(f"{st.frames} ({st.invalid})")
        w["ack"].setText(self._ack_text(st.last_ack))
        text, color = self._status_text(i)
        w["status"].setText(text)
        style.set_text_color(w["status"], color)

    def _update_status(self):
        now = time.monotonic()
        for i, st in enumerate(self._st):
            if (st.pending_cmd is not None and st.pending_cmd != "hw_zero"
                    and now - st.pending_since > _CMD_TIMEOUT_S):
                if st.reporting in ("pending_on", "pending_off"):
                    st.reporting = "unknown"
                st.pending_cmd = None
                st.last_ack = "timeout"
        for i in range(len(self._chan)):
            self._update_channel(i)

    # ── 生命周期 ──
    def on_activated(self):
        self._stale_timer.start()
        self._scope.start()

    def on_deactivating(self):
        self._stale_timer.stop()
        self._scope.stop()
        self._init_timer.stop()
        self._hz_timer.stop()
        self._init_stage = None
        self._hz_stage = None
        self._hz_target = None
        self._hz_restore = []
        if self._setid_busy and self._setid_task is not None:
            try:
                self._setid_task.cancel()
            except Exception:
                pass

    def on_connect(self):
        for st in self._st:
            st.reset()
        self._scope.clear()
        self._init_stage = None
        self._hz_stage = None
        self._hz_target = None
        self._hz_restore = []
        self._set_setid_status("Torque.SetId.Idle", style.FG_DIM)
        self._stale_timer.start()
        self._update_status()

        if self._ctx.is_fd_mode():
            self._ctx.status_message(_("Torque.Hint.Fd"), 4000)
        elif self._ctx.get_bitrate() != 1_000_000:
            self._ctx.status_message(_("Torque.Hint.Bitrate"), 4000)

        if self._auto_init_chk.isChecked():
            self._on_init_all()

    def on_disconnect(self):
        self._stale_timer.stop()
        self._init_timer.stop()
        self._hz_timer.stop()
        self._init_stage = None
        self._hz_stage = None
        self._hz_target = None
        self._hz_restore = []
        if self._setid_busy and self._setid_task is not None:
            try:
                self._setid_task.cancel()
            except Exception:
                pass
        self._setid_busy = False
        self._setid_buttons_enabled(True)
        self._set_setid_status("Torque.Status.Disconnected", style.FG_DIM)
        self._scope.clear()
        for st in self._st:
            st.reset()
        self._update_status()

    def refresh_language(self):
        for box, key in self._titles:
            box.setTitle(_(key))
        for widget, key in self._static:
            if isinstance(widget, QCheckBox):
                widget.setText(_(key))
            elif isinstance(widget, QPushButton):
                widget.setText(_(key))
            elif isinstance(widget, QLabel):
                widget.setText(_(key))
        self._rate_spin.setSuffix(" " + _("Torque.Unit.Hz"))
        self._scope.set_no_data_text(_("Torque.Scope.NoData"))
        self._update_scope_pause_text()
        self._render_setid_status()
        self._render_setid_current()
        self._update_status()
