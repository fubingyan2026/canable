"""柯力扭矩传感器监视面板（CAN V1.2）。

功能：连续/单次读取、AD 码值、三种归零 + 软件零点、参数查询/设置、
版本号查询、重启、单通道波形、CSV 记录、原始报文日志。
"""
from __future__ import annotations

import csv
import logging
import os
import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                                QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                                QMessageBox, QPushButton,
                                QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style
from cangui.plugin_ui import SectionPage, SectionTabs

from . import protocol as P
from .scope import DEFAULT_WINDOW_S, WINDOW_CHOICES, ValueScope

logger = logging.getLogger("plugin.keli_torque")


ACK_TIMEOUT_MS = 300
INFO_STEP_MS = 120
VERSION_WATCH_MS = 500
CSV_FLUSH_ROWS = 100
STALE_MIN_S = 1.0
RESTART_DELAY_MS = 2000
PROBE_INTERVAL_MS = 1000     # 掉线后每秒探测一次
PROBE_GRACE_S = 3.0          # 开流后多久没任何回帧即判定掉线


def _base_dir() -> str:
    """可执行文件所在目录（打包后）或工程根目录（源码运行）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


class _WheelSpin:
    """Mixin：滚轮始终按 singleStep 改值（不滚动外层滚动区）。"""

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if dy:
            notches = int(dy / 120.0)
            if notches == 0:
                notches = 1 if dy > 0 else -1
            self.stepBy(notches)
        ev.accept()


class _IntSpin(_WheelSpin, QSpinBox):
    pass


class _FloatSpin(_WheelSpin, QDoubleSpinBox):
    pass


_I18N_KEYS = {
    "Keli.Title":            ("柯力传感器",        "Keli Sensor"),
    "Keli.Config":           ("传感器配置",          "Sensor Config"),
    "Keli.Addr":             ("地址",                "Address"),
    "Keli.Interval":         ("发数间隔",            "Interval"),
    "Keli.AutoStart":        ("连接后自动开始采集",  "Auto-start on connect"),
    "Keli.Start":            ("开始采集",            "Start"),
    "Keli.Stop":             ("停止",                "Stop"),
    "Keli.Single":           ("单次读取",            "Single Read"),
    "Keli.ReadAd":           ("读 AD 码值",          "Read AD"),
    "Keli.ReadInfo":         ("读取信息",            "Read Info"),
    "Keli.Streaming":        ("采集中",              "Streaming"),
    "Keli.Offline":          ("无响应",              "No response"),
    "Keli.LastUpdate":       ("更新于",              "Updated at"),
    "Keli.Hint.Bus":         ("提示：该传感器为 Classic CAN / 1 Mbps（地址 1 → ID 0x522）",
                             "Hint: Classic CAN @ 1 Mbps (address 1 -> ID 0x522)"),

    "Keli.Value":            ("实时值",              "Live Value"),
    "Keli.Raw":              ("原始值",              "Raw"),
    "Keli.AdCode":           ("AD 码值",             "AD Code"),
    "Keli.Invalid":          ("无效帧",              "Invalid"),
    "Keli.Scale":            ("分度值",              "Scale"),
    "Keli.Filter":           ("滤波",                "Filter"),
    "Keli.Version":          ("版本",                "Version"),
    "Keli.Date":             ("日期",                "Date"),
    "Keli.Type":             ("类型码",              "Type"),
    "Keli.NoData":           ("—",                   "—"),
    "Keli.Unit.N":           ("N",                   "N"),
    "Keli.Unit.Ms":          ("ms",                  "ms"),
    "Keli.Unit.Times":       ("次",                  "times"),

    "Keli.Scope":            ("波形",                "Waveform"),
    "Keli.Window":           ("时间窗",              "Window"),
    "Keli.Pause":            ("暂停",                "Pause"),
    "Keli.Resume":           ("继续",                "Resume"),
    "Keli.Clear":            ("清除",                "Clear"),
    "Keli.ScopeNoData":      ("无数据",              "No data"),

    "Keli.Record":           ("记录到 CSV",          "Record to CSV"),
    "Keli.OpenCsv":          ("打开",                "Open"),
    "Keli.NoFile":           ("未记录",              "Not recording"),
    "Keli.Rows":             ("行",                  "rows"),
    "Keli.RecordCloseConfirm": ("正在记录 CSV，关闭面板将停止记录并关闭文件。继续？",
                               "CSV recording is active. Closing will stop recording and "
                               "close the file. Continue?"),

    "Keli.Params":           ("参数",                "Parameters"),
    "Keli.Query":            ("查询",                "Query"),
    "Keli.Set":              ("设置",                "Set"),
    "Keli.AdRate":           ("AD 采样率",           "AD Rate"),
    "Keli.AdGain":           ("增益",                "Gain"),
    "Keli.AdConfirm":        ("AD 参数影响测量链路，非必要不建议修改。确认写入 采样率 {rate} Hz / 增益 {gain}？",
                             "AD parameters affect the measurement chain. Write rate {rate} Hz "
                             "/ gain {gain}?"),
    "Keli.NewAddr":          ("新地址",              "New Address"),
    "Keli.SetAddr":          ("设置地址",            "Set Address"),
    "Keli.SetAddrConfirm":   ("确认把传感器地址改为 {addr}？改后必须把面板地址也改为 {addr}（ID 变为 0x{can_id:03X}），否则将无法通讯。",
                             "Change the sensor address to {addr}? You must also change the panel "
                             "address to {addr} (ID becomes 0x{can_id:03X}), otherwise it will be "
                             "unreachable."),
    "Keli.AddrChanged":      ("地址已改为 {addr}（ID 0x{can_id:03X}）",
                             "Address changed to {addr} (ID 0x{can_id:03X})"),

    "Keli.Maint":            ("标定与维护",          "Calibration & Maintenance"),
    "Keli.ZeroSave":         ("清 0（置零并保存）",  "Zero (save)"),
    "Keli.QueryVersion":     ("查询版本号",          "Query Version"),
    "Keli.Reset":            ("重启传感器",          "Restart"),
    "Keli.ZeroTitle":        ("归零确认",            "Zero Confirmation"),
    "Keli.ZeroSaveConfirm":  ("将把传感器当前输出记为零点并写入传感器（断电保存）。请确认已卸载、处于零位。继续？",
                             "The current output will be stored as zero in the sensor "
                             "(survives power-off). Make sure the load is removed and the "
                             "sensor is at zero. Continue?"),
    "Keli.ResetConfirm":     ("确认重启传感器？重启期间将短暂无数据。",
                             "Restart the sensor? Data will pause briefly."),
    "Keli.ResetSent":        ("已发送重启指令，2 s 后恢复采集",
                             "Restart command sent; resuming in 2 s"),

    "Keli.Ack.Ok":           ("指令正确",            "OK"),
    "Keli.Ack.BadCmd":       ("无效命令",            "Invalid command"),
    "Keli.Ack.BadParam":     ("非法参数",            "Invalid parameter"),
    "Keli.Ack.StoreFail":    ("存储失败",            "Store failed"),
    "Keli.Ack.Unknown":      ("未知状态 0x{code:02X}", "Unknown status 0x{code:02X}"),
    "Keli.Ack.Timeout":      ("应答超时（传感器无响应）",
                             "Ack timeout (no response)"),
    "Keli.Cmd.SetInterval":  ("设置发数间隔",        "Set interval"),
    "Keli.Cmd.SetScale":     ("设置分度值",          "Set scale"),
    "Keli.Cmd.SetFilter":    ("设置滤波",            "Set filter"),
    "Keli.Cmd.SetAd":        ("设置 AD 参数",        "Set AD params"),
    "Keli.Cmd.SetAddr":      ("设置地址",            "Set address"),
    "Keli.Cmd.ZeroSave":     ("置零",                "Zero"),

    "Keli.Err.NotConnected": ("CAN 未连接，请先在主界面连接设备",
                             "CAN not connected. Connect a device first."),
    "Keli.Err.Busy":         ("上一条指令还在等待应答，请稍候",
                             "Waiting for the previous command's ack"),
    "Keli.Err.OpenCsv":      ("没有可打开的记录文件", "No recording file to open"),
    "Keli.Hint.OtherAddr":   ("检测到地址 {addr} 的帧（ID 0x{can_id:03X}），请把面板地址改为 {addr}",
                             "Frames seen on address {addr} (ID 0x{can_id:03X}); "
                             "set the panel address to {addr}"),
    "Keli.VersionSent":      ("已发送版本查询，等待应答…",
                             "Version query sent, waiting for reply…"),
    "Keli.VersionRetry":     ("版本查询无应答，正在重试一次…",
                             "No version reply, retrying once…"),
    "Keli.VersionNoReply":   ("版本查询无应答（传感器未响应 51 09；请确认地址与波特率）",
                             "No version reply (sensor did not answer 51 09; "
                             "check address and bitrate)"),
    "Keli.OfflineProbing":   ("离线 · 自动探测中（等待传感器热插拔恢复）",
                             "Offline · probing (waiting for the sensor)"),
    "Keli.LinkLost":         ("传感器无响应，已进入自动探测",
                             "Sensor not responding; auto-probing"),
    "Keli.LinkRestored":     ("传感器已恢复，正在重新初始化…",
                             "Sensor restored, re-initializing…"),
}


class _ConfigStore:
    PLUGIN_NAME = "keli_torque"
    DEFAULTS = {
        "addr": P.DEFAULT_ADDR,
        "interval_ms": P.DEFAULT_INTERVAL_MS,
        "auto_start": True,
        "record": False,
        "scope_window": float(DEFAULT_WINDOW_S),
        "scale_code": P.DEFAULT_SCALE_CODE,
        "filter_level": P.DEFAULT_FILTER,
        "ad_rate": P.DEFAULT_AD_RATE,
        "ad_gain": P.DEFAULT_AD_GAIN,
        "new_addr": P.DEFAULT_ADDR,
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


class KeliPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)

        self._streaming = False
        self._pending = None            # (ack_key, started_monotonic)
        self._pending_addr = None
        self._start_after_pending = False
        self._last_raw = None
        self._last_rx = 0.0
        self._invalid = 0
        # 查询与连续流互斥：查询前暂停流，查完恢复（部分固件在流状态下不响应查询）
        self._query_queue = []
        self._query_stage = 0
        self._resume_after_query = False
        self._version_retry_done = False
        # 热插拔：链路状态 + 期望采集状态
        self._link_up = False
        self._want_stream = False
        self._stream_since = 0.0
        self._csv_file = None
        self._csv_writer = None
        self._csv_rows = 0
        self._csv_t0 = 0.0
        self._csv_path = ""

        # 诊断（单行显示最近一帧，不刷屏；用于区分“收不到/地址不对/解析失败”）
        self._rx_count = 0
        self._last_frame_hex = ""
        self._last_frame_kind = ""
        self._other_addrs = {}
        self._unparsed_logged = 0
        self._first_value_logged = False
        self._autostart_pending = False

        self._static = []
        self._titles = []
        self._ack_buttons = []
        self._maint_buttons = []

        self._build_ui()
        self._load_config()

        self._ack_timer = QTimer(self)
        self._ack_timer.setSingleShot(True)
        self._ack_timer.timeout.connect(self._on_ack_timeout)
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.timeout.connect(self._on_query_timer)
        self._version_timer = QTimer(self)
        self._version_timer.setSingleShot(True)
        self._version_timer.timeout.connect(self._on_version_timeout)
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(PROBE_INTERVAL_MS)
        self._probe_timer.timeout.connect(self._on_probe_tick)
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._on_stale_tick)
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._on_restart_timeout)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._on_start)

        self._update_buttons()
        self._update_status()
        self._update_diag()
        self._update_record_label()

    # ── 构建辅助 ──
    def _label(self, key: str) -> QLabel:
        lbl = QLabel(_(key))
        self._static.append((lbl, key))
        return lbl

    def _unit(self, key: str, width: int = 36) -> QLabel:
        lbl = QLabel(_(key))
        style.set_text_color(lbl, style.FG_DIM)
        lbl.setFixedWidth(width)
        self._static.append((lbl, key))
        return lbl

    def _group(self, key: str, page=False):
        box = SectionPage(_(key)) if page else QGroupBox(_(key))
        self._titles.append((box, key))
        return box

    def _button(self, key: str, slot, ack: bool = False) -> QPushButton:
        btn = QPushButton(_(key))
        btn.clicked.connect(slot)
        self._static.append((btn, key))
        if ack:
            self._ack_buttons.append(btn)
        return btn

    # ── UI ──
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
        root.addWidget(self._build_value())
        self._detail_tabs = SectionTabs()
        for page in (self._build_scope(), self._build_params(),
                     self._build_record(), self._build_maint()):
            self._detail_tabs.add_section(page)
        root.addWidget(self._detail_tabs, 1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_config(self) -> QGroupBox:
        box = self._group("Keli.Config")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)

        g.addWidget(self._label("Keli.Addr"), 0, 0)
        self._addr_spin = _IntSpin()
        self._addr_spin.setRange(P.ADDR_MIN, P.ADDR_MAX)
        self._addr_spin.setValue(P.DEFAULT_ADDR)
        self._addr_spin.valueChanged.connect(self._on_addr_changed)
        g.addWidget(self._addr_spin, 0, 1)
        self._id_label = QLabel()
        style.set_text_color(self._id_label, style.FG_DIM)
        g.addWidget(self._id_label, 0, 2, 1, 2)

        self._status_label = QLabel(_("Keli.NoData"))
        style.set_text_color(self._status_label, style.FG_DIM)
        g.addWidget(self._status_label, 0, 4, 1, 3)

        g.addWidget(self._label("Keli.Interval"), 1, 0)
        self._interval_spin = _IntSpin()
        self._interval_spin.setRange(P.INTERVAL_MIN_MS, P.INTERVAL_MAX_MS)
        self._interval_spin.setSingleStep(10)
        self._interval_spin.setValue(P.DEFAULT_INTERVAL_MS)
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        g.addWidget(self._interval_spin, 1, 1)
        g.addWidget(self._unit("Keli.Unit.Ms"), 1, 2)

        self._start_btn = self._button("Keli.Start", self._on_start, ack=True)
        g.addWidget(self._start_btn, 1, 3)
        self._stop_btn = self._button("Keli.Stop", self._on_stop)
        g.addWidget(self._stop_btn, 1, 4)
        self._single_btn = self._button("Keli.Single", self._on_single)
        g.addWidget(self._single_btn, 1, 5)
        self._ad_btn = self._button("Keli.ReadAd", self._on_read_ad)
        g.addWidget(self._ad_btn, 1, 6)
        self._info_btn = self._button("Keli.ReadInfo", self._on_read_info)
        g.addWidget(self._info_btn, 1, 7)

        self._auto_start_chk = QCheckBox(_("Keli.AutoStart"))
        self._auto_start_chk.setChecked(True)
        self._auto_start_chk.toggled.connect(self._on_auto_start_changed)
        self._static.append((self._auto_start_chk, "Keli.AutoStart"))
        g.addWidget(self._auto_start_chk, 0, 7, 1, 2)
        g.setColumnStretch(8, 1)
        return box

    def _build_value(self) -> QGroupBox:
        box = self._group("Keli.Value")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)

        self._big_value = QLabel(_("Keli.NoData"))
        big = QFont()
        big.setPointSize(max(18, big.pointSize() + 12))
        big.setBold(True)
        self._big_value.setFont(big)
        style.set_text_color(self._big_value, style.LOAD_LOW)
        g.addWidget(self._big_value, 0, 0, 1, 2)
        self._big_unit = self._unit("Keli.Unit.N", 30)
        style.set_text_color(self._big_unit, style.FG_DIM, 'font-weight: 600;')
        g.addWidget(self._big_unit, 0, 2)

        self._fields = {}
        # 只显示参数区没有的信息（分度值/滤波/地址等在“参数”区已有，不再重复）
        row = (
            ("raw", "Keli.Raw", "Keli.Unit.N"),
            ("ad", "Keli.AdCode", ""),
            ("invalid", "Keli.Invalid", "Keli.Unit.Times"),
            ("version", "Keli.Version", ""),
            ("date", "Keli.Date", ""),
            ("type", "Keli.Type", ""),
        )
        for i, (key, label_key, unit_key) in enumerate(row):
            r = 1 + i // 3
            c = (i % 3) * 3
            g.addWidget(self._label(label_key), r, c)
            val = QLabel(_("Keli.NoData"))
            style.set_text_color(val, style.FG_TEXT, 'font-weight: 600;')
            g.addWidget(val, r, c + 1)
            if unit_key:
                g.addWidget(self._unit(unit_key), r, c + 2)
            else:
                g.addWidget(self._unit(""), r, c + 2)
            self._fields[key] = val

        # 诊断行：RX 计数 / 最近一帧 / 解析类型（单行覆盖更新，不做滚动日志）
        self._diag_label = QLabel(_("Keli.NoData"))
        style.set_text_color(self._diag_label, style.FG_DIM)
        g.addWidget(self._diag_label, 1 + (len(row) + 2) // 3, 0, 1, 9)
        g.setColumnStretch(9, 1)
        return box

    def _build_scope(self) -> QWidget:
        box = self._group("Keli.Scope", page=True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.addWidget(self._label("Keli.Window"))
        self._window_combo = QComboBox()
        for seconds in WINDOW_CHOICES:
            self._window_combo.addItem("%d s" % int(seconds), float(seconds))
        self._window_combo.currentIndexChanged.connect(self._on_window_changed)
        row.addWidget(self._window_combo)
        row.addSpacing(10)
        self._pause_btn = QPushButton(_("Keli.Pause"))
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause_toggled)
        row.addWidget(self._pause_btn)
        row.addWidget(self._button("Keli.Clear", self._on_scope_clear))
        row.addStretch(1)
        lay.addLayout(row)

        self._scope = ValueScope(_("Keli.Title"), style.FG_ACCENT, "N")
        self._scope.set_no_data_text(_("Keli.ScopeNoData"))
        lay.addWidget(self._scope, 1)
        return box

    def _build_record(self) -> QWidget:
        box = self._group("Keli.Record", page=True)
        row = QHBoxLayout(box)
        row.setAlignment(Qt.AlignTop)
        row.setContentsMargins(8, 6, 8, 6)
        self._record_chk = QCheckBox(_("Keli.Record"))
        self._record_chk.toggled.connect(self._on_record_toggled)
        self._static.append((self._record_chk, "Keli.Record"))
        row.addWidget(self._record_chk)
        self._record_label = QLabel(_("Keli.NoFile"))
        style.set_text_color(self._record_label, style.FG_DIM)
        row.addWidget(self._record_label)
        row.addStretch(1)
        self._open_btn = self._button("Keli.OpenCsv", self._on_open_csv)
        row.addWidget(self._open_btn)
        return box

    def _build_params(self) -> QWidget:
        box = self._group("Keli.Params", page=True)
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        g.setAlignment(Qt.AlignTop)

        g.addWidget(self._label("Keli.Scale"), 0, 0)
        self._scale_combo = QComboBox()
        for code, nm in P.SCALE_OPTIONS:
            self._scale_combo.addItem("%g N" % nm, int(code))
        g.addWidget(self._scale_combo, 0, 1)
        g.addWidget(self._button("Keli.Query", self._on_query_scale), 0, 2)
        g.addWidget(self._button("Keli.Set", self._on_set_scale, ack=True), 0, 3)

        g.addWidget(self._label("Keli.Filter"), 0, 4)
        self._filter_spin = _IntSpin()
        self._filter_spin.setRange(P.FILTER_MIN, P.FILTER_MAX)
        g.addWidget(self._filter_spin, 0, 5)
        g.addWidget(self._button("Keli.Query", self._on_query_filter), 0, 6)
        g.addWidget(self._button("Keli.Set", self._on_set_filter, ack=True), 0, 7)

        g.addWidget(self._label("Keli.Interval"), 1, 0)
        self._param_interval_spin = _IntSpin()
        self._param_interval_spin.setRange(P.INTERVAL_MIN_MS, P.INTERVAL_MAX_MS)
        self._param_interval_spin.setSingleStep(10)
        g.addWidget(self._param_interval_spin, 1, 1)
        g.addWidget(self._button("Keli.Query", self._on_query_interval), 1, 2)
        g.addWidget(self._button("Keli.Set", self._on_set_interval, ack=True), 1, 3)

        g.addWidget(self._label("Keli.AdRate"), 1, 4)
        self._ad_rate_combo = QComboBox()
        for rate in P.AD_RATES:
            self._ad_rate_combo.addItem("%d Hz" % rate, int(rate))
        g.addWidget(self._ad_rate_combo, 1, 5)
        g.addWidget(self._label("Keli.AdGain"), 1, 6)
        self._ad_gain_combo = QComboBox()
        for gain in P.AD_GAINS:
            self._ad_gain_combo.addItem(str(gain), int(gain))
        g.addWidget(self._ad_gain_combo, 1, 7)
        g.addWidget(self._button("Keli.Query", self._on_query_ad), 2, 6)
        g.addWidget(self._button("Keli.Set", self._on_set_ad, ack=True), 2, 7)

        g.addWidget(self._label("Keli.NewAddr"), 2, 0)
        self._new_addr_spin = _IntSpin()
        self._new_addr_spin.setRange(P.ADDR_MIN, P.ADDR_MAX)
        g.addWidget(self._new_addr_spin, 2, 1)
        g.addWidget(self._button("Keli.SetAddr", self._on_set_addr, ack=True),
                    2, 2, 1, 2)
        g.setColumnStretch(8, 1)
        return box

    def _build_maint(self) -> QWidget:
        box = self._group("Keli.Maint", page=True)
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        g.setAlignment(Qt.AlignTop)

        zero_save = self._button("Keli.ZeroSave", self._on_zero_save, ack=True)
        g.addWidget(zero_save, 0, 0)
        g.addWidget(self._button("Keli.QueryVersion", self._on_query_version), 0, 1)
        g.addWidget(self._button("Keli.Reset", self._on_reset), 0, 2)
        g.setColumnStretch(3, 1)

        self._maint_buttons = [b for b in (zero_save,) if b is not None]
        return box

    # ── 配置 ──
    def _load_config(self):
        widgets = (
            (self._addr_spin, "addr"),
            (self._auto_start_chk, "auto_start"),
            (self._interval_spin, "interval_ms"),
            (self._record_chk, "record"),
            (self._scale_combo, "scale_code"),
            (self._filter_spin, "filter_level"),
            (self._ad_rate_combo, "ad_rate"),
            (self._ad_gain_combo, "ad_gain"),
            (self._new_addr_spin, "new_addr"),
        )
        for widget, key in widgets:
            widget.blockSignals(True)
            value = self._cfg.get(key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                idx = widget.findData(int(value))
                widget.setCurrentIndex(max(0, idx))
            else:
                widget.setValue(int(value))
            widget.blockSignals(False)

        self._param_interval_spin.blockSignals(True)
        self._param_interval_spin.setValue(int(self._cfg.get("interval_ms")))
        self._param_interval_spin.blockSignals(False)

        win = float(self._cfg.get("scope_window"))
        idx = self._window_combo.findData(win)
        self._window_combo.blockSignals(True)
        self._window_combo.setCurrentIndex(
            max(0, idx if idx >= 0 else self._window_combo.findData(DEFAULT_WINDOW_S)))
        self._window_combo.blockSignals(False)
        self._scope.set_window(float(self._window_combo.currentData()))

        self._new_addr_spin.blockSignals(True)
        self._new_addr_spin.setValue(int(self._cfg.get("addr")))
        self._new_addr_spin.blockSignals(False)

        self._update_id_label()

    def _addr(self) -> int:
        return int(self._addr_spin.value())

    def _update_id_label(self):
        self._id_label.setText("TX = RX = 0x%03X" % P.can_id(self._addr()))

    def _on_addr_changed(self, value: int):
        self._cfg.set("addr", int(value))
        self._new_addr_spin.blockSignals(True)
        self._new_addr_spin.setValue(int(value))
        self._new_addr_spin.blockSignals(False)
        self._update_id_label()

    def _on_interval_changed(self, value: int):
        self._cfg.set("interval_ms", int(value))
        self._param_interval_spin.blockSignals(True)
        self._param_interval_spin.setValue(int(value))
        self._param_interval_spin.blockSignals(False)

    def _on_auto_start_changed(self, checked: bool):
        self._cfg.set("auto_start", bool(checked))

    def _on_window_changed(self, _index: int):
        win = float(self._window_combo.currentData())
        self._cfg.set("scope_window", win)
        self._scope.set_window(win)

    # ── 发送 ──
    def _ensure_connected(self) -> bool:
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Keli.Err.NotConnected"), 3000)
            return False
        return True

    def _send(self, payload: bytes, ack_key: str | None = None) -> bool:
        if not self._ensure_connected():
            return False
        if ack_key is not None:
            if self._pending is not None:
                self._ctx.status_message(_("Keli.Err.Busy"), 3000)
                return False
            self._pending = (ack_key, time.monotonic())
            self._ack_timer.start(ACK_TIMEOUT_MS)
            self._apply_busy(True)
        self._ctx.send_frame(P.frame(self._addr(), payload))
        logger.info("TX id=0x%03X data=%s", P.can_id(self._addr()),
                    payload.hex(" "))
        return True

    def _apply_busy(self, busy: bool):
        for btn in self._ack_buttons:
            btn.setEnabled(self._ctx.is_connected() and not busy)

    # ── 采集 ──
    def _on_start(self):
        if not self._ensure_connected() or self._streaming:
            return
        self._want_stream = True          # 期望状态：热插拔后按此恢复
        self._probe_timer.stop()
        if self._pending is not None:
            # 还有指令在等应答：直接开流（间隔沿用当前值），避免叠加 pending
            self._send_stream_start()
            return
        ms = int(self._interval_spin.value())
        self._start_after_pending = True
        self._send(P.build_set_interval(self._addr(), ms),
                   ack_key="interval_for_start")

    def _send_stream_start(self):
        if not self._ensure_connected():
            return
        self._send(P.build_start_continuous(self._addr()))
        self._streaming = True
        self._want_stream = True
        self._last_rx = 0.0
        self._stream_since = time.monotonic()
        self._probe_timer.stop()
        self._update_buttons()
        self._ctx.status_message(_("Keli.Streaming"), 3000)
        self._update_status()

    def _stop_stream(self, send: bool = True):
        if send and self._streaming and self._ctx.is_connected():
            self._send(P.build_stop(self._addr()))
        self._streaming = False
        self._start_after_pending = False   # 取消等待应答后的自动开流
        self._autostart_pending = False      # 取消查询后的自动开流
        self._resume_after_query = False
        self._query_queue = []
        self._query_stage = 0
        self._query_timer.stop()
        self._version_timer.stop()
        self._probe_timer.stop()
        self._start_timer.stop()
        self._restart_timer.stop()          # 取消重启后的自动恢复
        self._update_buttons()
        self._update_status()

    def _on_stop(self):
        self._want_stream = False          # 用户主动停止：不再自动恢复
        self._probe_timer.stop()
        self._stop_stream(send=True)

    def _on_single(self):
        self._send(P.build_single_read(self._addr()))

    def _on_read_ad(self):
        self._send(P.build_read_ad(self._addr()))

    def _on_read_info(self):
        addr = self._addr()
        self._query_with_pause([P.build_query_version(addr),
                                P.build_query_interval(addr),
                                P.build_query_addr(addr)])

    def _query_with_pause(self, payloads, autostart: bool = False):
        """发送查询前先暂停连续流（部分固件在流状态下不响应查询），发完再恢复。

        autostart=True 时不恢复流，而是查询结束后开始采集（连接初始化用）。
        """
        if not self._ensure_connected():
            self._autostart_pending = False
            return
        self._resume_after_query = self._streaming and not autostart
        self._autostart_pending = bool(autostart)
        if self._streaming:
            self._send(P.build_stop(self._addr()))
            self._streaming = False
            self._update_buttons()
            self._update_status()
        self._query_queue = list(payloads)
        self._query_stage = 0
        self._query_timer.start(60)      # 先让传感器处理“停止取数”

    def _on_query_timer(self):
        if not self._ctx.is_connected():
            self._query_queue = []
            self._query_stage = 0
            self._resume_after_query = False
            self._autostart_pending = False
            return
        if self._query_stage == 0:
            if self._query_queue:
                payload = self._query_queue.pop(0)
                self._ctx.send_frame(P.frame(self._addr(), payload))
                logger.info("TX id=0x%03X data=%s", P.can_id(self._addr()),
                            payload.hex(" "))
                if payload == P.build_query_version(self._addr()):
                    # 版本查询限时观察：无应答则重试一次，再失败给出明确提示
                    self._version_retry_done = False
                    self._version_timer.start(VERSION_WATCH_MS)
                self._query_timer.start(INFO_STEP_MS)
                return
            self._query_stage = 1
            self._query_timer.start(220)     # 留时间收应答
            return
        # stage 1：收尾
        self._query_stage = 0
        if self._resume_after_query:
            self._resume_after_query = False
            self._send_stream_start()
        elif self._autostart_pending:
            self._autostart_pending = False
            self._on_start()

    def _on_version_timeout(self):
        if not self._ctx.is_connected():
            return
        if not self._version_retry_done:
            self._version_retry_done = True
            self._ctx.status_message(_("Keli.VersionRetry"), 3000)
            logger.info("version query retry")
            payload = P.build_query_version(self._addr())
            self._ctx.send_frame(P.frame(self._addr(), payload))
            self._version_timer.start(VERSION_WATCH_MS)
            return
        self._ctx.status_message(_("Keli.VersionNoReply"), 6000)
        logger.warning("version query: no reply (addr=%d id=0x%03X)",
                       self._addr(), P.can_id(self._addr()))

    # ── 应答 ──
    def _on_ack_timeout(self):
        key = self._pending[0] if self._pending else ""
        self._pending = None
        self._apply_busy(False)
        self._ctx.status_message(_("Keli.Ack.Timeout"), 4000)
        if self._start_after_pending:
            self._start_after_pending = False
            self._send_stream_start()
        logger.warning("ack timeout for %s", key)

    def _resolve_ack(self, status: int):
        key = self._pending[0] if self._pending else ""
        self._pending = None
        self._ack_timer.stop()
        self._apply_busy(False)

        if status == P.ACK_OK:
            text = _("Keli.Ack.Ok")
        elif status == P.ACK_BAD_CMD:
            text = _("Keli.Ack.BadCmd")
        elif status == P.ACK_BAD_PARAM:
            text = _("Keli.Ack.BadParam")
        elif status == P.ACK_STORE_FAIL:
            text = _("Keli.Ack.StoreFail")
        else:
            text = _("Keli.Ack.Unknown").format(code=status)

        label_key = {
            "interval_for_start": "Keli.Cmd.SetInterval",
            "set_interval": "Keli.Cmd.SetInterval",
            "set_scale": "Keli.Cmd.SetScale",
            "set_filter": "Keli.Cmd.SetFilter",
            "set_ad": "Keli.Cmd.SetAd",
            "set_addr": "Keli.Cmd.SetAddr",
            "zero_save": "Keli.Cmd.ZeroSave",
        }.get(key)
        prefix = _(label_key) if label_key else ""
        self._ctx.status_message(("%s: %s" % (prefix, text)) if prefix else text, 4000)

        if status == P.ACK_OK:
            if key == "set_addr" and self._pending_addr is not None:
                new_addr = int(self._pending_addr)
                self._pending_addr = None
                self._addr_spin.blockSignals(True)
                self._addr_spin.setValue(new_addr)
                self._addr_spin.blockSignals(False)
                self._cfg.set("addr", new_addr)
                self._update_id_label()
                self._ctx.status_message(_("Keli.AddrChanged").format(
                    addr=new_addr, can_id=P.can_id(new_addr)), 6000)

        if self._start_after_pending:
            self._start_after_pending = False
            self._send_stream_start()

    # ── 归零 ──
    def _confirm(self, title_key: str, text_key: str, **params) -> bool:
        text = _(text_key)
        if params:
            try:
                text = text.format(**params)
            except Exception:
                pass
        ret = QMessageBox.warning(
            self, _(title_key), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return ret == QMessageBox.StandardButton.Yes

    def _on_zero_save(self):
        if not self._ensure_connected():
            return
        if not self._confirm("Keli.ZeroTitle", "Keli.ZeroSaveConfirm"):
            return
        self._send(P.build_zero_save(self._addr()), ack_key="zero_save")

    # ── 版本 / 重启 / 地址 ──
    def _on_query_version(self):
        self._ctx.status_message(_("Keli.VersionSent"), 3000)
        self._query_with_pause([P.build_query_version(self._addr())])

    def _on_reset(self):
        if not self._ensure_connected():
            return
        if not self._confirm("Keli.Maint", "Keli.ResetConfirm"):
            return
        was_streaming = self._streaming
        self._send(P.build_reset(self._addr()))
        self._streaming = False
        self._update_buttons()
        self._update_status()
        self._ctx.status_message(_("Keli.ResetSent"), 4000)
        if was_streaming and self._auto_start_chk.isChecked():
            self._restart_timer.start(RESTART_DELAY_MS)

    def _on_restart_timeout(self):
        if self._ctx.is_connected() and self._auto_start_chk.isChecked():
            self._on_start()

    def _on_set_addr(self):
        if not self._ensure_connected():
            return
        new_addr = int(self._new_addr_spin.value())
        if not self._confirm("Keli.SetAddr", "Keli.SetAddrConfirm",
                             addr=new_addr, can_id=P.can_id(new_addr)):
            return
        self._pending_addr = new_addr
        if not self._send(P.build_set_addr(self._addr(), new_addr),
                          ack_key="set_addr"):
            self._pending_addr = None

    # ── 参数 ──
    def _on_query_scale(self):
        self._query_with_pause([P.build_query_scale(self._addr())])

    def _on_set_scale(self):
        code = int(self._scale_combo.currentData())
        self._cfg.set("scale_code", code)
        self._send(P.build_set_scale(self._addr(), code), ack_key="set_scale")

    def _on_query_filter(self):
        self._query_with_pause([P.build_query_filter(self._addr())])

    def _on_set_filter(self):
        level = int(self._filter_spin.value())
        self._cfg.set("filter_level", level)
        self._send(P.build_set_filter(self._addr(), level), ack_key="set_filter")

    def _on_query_interval(self):
        self._query_with_pause([P.build_query_interval(self._addr())])

    def _on_set_interval(self):
        ms = int(self._param_interval_spin.value())
        self._interval_spin.blockSignals(True)
        self._interval_spin.setValue(ms)
        self._interval_spin.blockSignals(False)
        self._cfg.set("interval_ms", ms)
        self._send(P.build_set_interval(self._addr(), ms), ack_key="set_interval")

    def _on_query_ad(self):
        self._query_with_pause([P.build_query_ad(self._addr())])

    def _on_set_ad(self):
        rate = int(self._ad_rate_combo.currentData())
        gain = int(self._ad_gain_combo.currentData())
        if not self._confirm("Keli.Params", "Keli.AdConfirm", rate=rate, gain=gain):
            return
        self._cfg.set("ad_rate", rate)
        self._cfg.set("ad_gain", gain)
        self._send(P.build_set_ad(self._addr(), rate, gain), ack_key="set_ad")

    # ── 接收 ──
    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        target = P.can_id(self._addr())
        for f in frames:
            if getattr(f, "is_tx", False) or f.is_error:
                continue
            cid = f.can_id
            if cid == target:
                self._rx_count += 1
                self._last_frame_hex = " ".join("%02X" % b for b in f.data)
                self._mark_link_up()
                res = P.parse(f.data)
                if res is None:
                    self._last_frame_kind = "unparsed"
                    if self._unparsed_logged < 3:
                        logger.info("unparsed frame id=0x%03X data=%s",
                                    cid, f.data.hex(" "))
                        self._unparsed_logged += 1
                    continue
                self._last_frame_kind = res.kind
                self._handle(res, f)
            elif P.ID_BASE + P.ADDR_MIN <= cid <= P.ID_BASE + P.ADDR_MAX:
                # 其它地址的帧：多半是面板地址与传感器不一致
                other = cid - P.ID_BASE
                self._other_addrs[other] = self._other_addrs.get(other, 0) + 1
                if sum(self._other_addrs.values()) <= 3:
                    logger.info("frame on address %d (id=0x%03X) data=%s",
                                other, cid, f.data.hex(" "))

    def _handle(self, res: P.Parsed, f):
        if res.kind == P.K_FORCE:
            self._last_raw = res.value
            self._last_rx = time.monotonic()
            if not self._first_value_logged:
                logger.info("first force sample: %.4f (data=%s)",
                            res.value, f.data.hex(" "))
                self._first_value_logged = True
            self._scope.add_sample(f.timestamp, res.value)
            self._csv_append(res.value)
            self._update_value()
            self._update_status()
            self._update_diag()
        elif res.kind == P.K_INVALID:
            self._invalid += 1
            self._update_value()
        elif res.kind == P.K_ACK:
            self._resolve_ack(res.status)
        elif res.kind == P.K_AD:
            self._fields["ad"].setText(str(res.raw_int))
        elif res.kind == P.K_SCALE:
            self._scale_combo.blockSignals(True)
            self._scale_combo.setCurrentIndex(
                max(0, self._scale_combo.findData(res.byte_val)))
            self._scale_combo.blockSignals(False)
        elif res.kind == P.K_FILTER:
            self._filter_spin.blockSignals(True)
            self._filter_spin.setValue(res.byte_val)
            self._filter_spin.blockSignals(False)
        elif res.kind == P.K_INTERVAL:
            ms = int(round(P.raw_to_ms(res.interval_raw)))
            self._param_interval_spin.blockSignals(True)
            self._param_interval_spin.setValue(ms)
            self._param_interval_spin.blockSignals(False)
            self._interval_spin.blockSignals(True)
            self._interval_spin.setValue(ms)
            self._interval_spin.blockSignals(False)
        elif res.kind == P.K_ADPARAMS:
            self._ad_rate_combo.blockSignals(True)
            self._ad_rate_combo.setCurrentIndex(
                max(0, self._ad_rate_combo.findData(res.rate)))
            self._ad_rate_combo.blockSignals(False)
            self._ad_gain_combo.blockSignals(True)
            self._ad_gain_combo.setCurrentIndex(
                max(0, self._ad_gain_combo.findData(res.gain)))
            self._ad_gain_combo.blockSignals(False)
        elif res.kind == P.K_VERSION:
            v = res.version
            self._version_timer.stop()
            self._version_retry_done = False
            logger.info("version reply: type=0x%02X version=%d date=%s",
                        v.type_code, v.version,
                        v.date_text if v.has_date else "-")
            self._fields["version"].setText(str(v.version))
            self._fields["date"].setText(
                v.date_text if v.has_date else _("Keli.NoData"))
            self._fields["type"].setText("0x%02X" % v.type_code)

    # ── 显示 ──
    def _update_value(self):
        if self._last_raw is None:
            self._big_value.setText(_("Keli.NoData"))
            self._fields["raw"].setText(_("Keli.NoData"))
        else:
            self._big_value.setText("%+.3f" % self._last_raw)
            self._fields["raw"].setText("%+.3f" % self._last_raw)
        self._fields["invalid"].setText(str(self._invalid))

    def _update_status(self):
        if not self._ctx.is_connected():
            self._status_label.setText(_("Keli.Err.NotConnected"))
            style.set_text_color(self._status_label, style.FG_DIM)
            return
        if not self._want_stream and not self._streaming:
            self._status_label.setText(_("Keli.NoData"))
            style.set_text_color(self._status_label, style.FG_DIM)
            return
        if not self._link_up:
            # 已掉线：看门狗在后台每秒探测，传感器恢复后自动重新初始化
            self._status_label.setText(_("Keli.OfflineProbing"))
            style.set_text_color(self._status_label, style.LOAD_MID)
            return
        stale_s = max(STALE_MIN_S, 5.0 * max(1, int(self._interval_spin.value())) / 1000.0)
        if self._last_rx and (time.monotonic() - self._last_rx) <= stale_s:
            self._status_label.setText("%s · %s %s" % (
                _("Keli.Streaming"), _("Keli.LastUpdate"),
                datetime.now().strftime("%H:%M:%S")))
            style.set_text_color(self._status_label, style.LOAD_LOW)
        else:
            self._status_label.setText(_("Keli.Offline"))
            style.set_text_color(self._status_label, style.LOAD_MID)

    # ── 热插拔：链路看门狗 + 自动探测 + 自动恢复 ──
    def _mark_link_up(self):
        if self._link_up:
            return
        self._link_up = True
        self._probe_timer.stop()
        logger.info("link up (addr=%d id=0x%03X)", self._addr(),
                    P.can_id(self._addr()))
        if self._want_stream and not self._streaming:
            self._on_link_restored()

    def _mark_link_down(self):
        if not self._link_up and not self._streaming:
            return
        self._link_up = False
        self._streaming = False
        self._cmd_epoch_stop()
        if self._want_stream and self._ctx.is_connected():
            self._probe_timer.start()
        self._ctx.status_message(_("Keli.LinkLost"), 4000)
        logger.warning("link down (addr=%d id=0x%03X), probing",
                       self._addr(), P.can_id(self._addr()))
        self._update_buttons()
        self._update_status()

    def _cmd_epoch_stop(self):
        """掉线后作废所有等待中的应答/查询/恢复定时器。"""
        self._pending = None
        self._ack_timer.stop()
        self._apply_busy(False)
        self._query_timer.stop()
        self._version_timer.stop()
        self._query_queue = []
        self._query_stage = 0
        self._resume_after_query = False
        self._autostart_pending = False
        self._start_after_pending = False
        self._start_timer.stop()

    def _on_link_restored(self):
        self._ctx.status_message(_("Keli.LinkRestored"), 4000)
        addr = self._addr()
        self._query_with_pause([P.build_query_version(addr),
                                P.build_query_interval(addr),
                                P.build_query_addr(addr)],
                               autostart=True)

    def _on_probe_tick(self):
        if not self._ctx.is_connected() or not self._want_stream:
            self._probe_timer.stop()
            return
        if self._link_up:
            self._probe_timer.stop()
            return
        payload = P.build_single_read(self._addr())
        self._ctx.send_frame(P.frame(self._addr(), payload))
        logger.info("probe id=0x%03X", P.can_id(self._addr()))

    def _update_buttons(self):
        connected = self._ctx.is_connected()
        self._start_btn.setEnabled(connected and not self._streaming)
        self._stop_btn.setEnabled(connected and self._streaming)
        self._single_btn.setEnabled(connected)
        self._ad_btn.setEnabled(connected)
        self._info_btn.setEnabled(connected)
        for btn in self._ack_buttons:
            btn.setEnabled(connected and self._pending is None)
        self._pause_btn.setEnabled(True)

    def _update_diag(self):
        """单行诊断：RX 计数 / 最近一帧 / 解析类型 / 地址提示。"""
        parts = ["RX %d" % self._rx_count]
        if self._last_frame_hex:
            parts.append("last 0x%03X [%s]" % (P.can_id(self._addr()),
                                              self._last_frame_hex))
        if self._last_frame_kind:
            parts.append("parse=%s" % self._last_frame_kind)
        if self._rx_count == 0 and self._other_addrs:
            addr = max(self._other_addrs, key=self._other_addrs.get)
            parts.append(_("Keli.Hint.OtherAddr").format(
                addr=addr, can_id=P.can_id(addr)))
        self._diag_label.setText("  ·  ".join(parts))

    # ── CSV ──
    def _on_record_toggled(self, checked: bool):
        self._cfg.set("record", bool(checked))
        if checked:
            self._csv_start()
        else:
            self._csv_stop()
        self._update_record_label()

    def _csv_start(self):
        if self._csv_writer is not None:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_base_dir(), "keli_%d_%s.csv" % (self._addr(), stamp))
        try:
            fh = open(path, "w", newline="", encoding="utf-8-sig")
            writer = csv.writer(fh)
            writer.writerow(["iso_time", "t_s", "value"])
        except OSError as exc:
            logger.warning("create csv failed: %s", exc)
            return
        self._csv_file = fh
        self._csv_writer = writer
        self._csv_rows = 0
        self._csv_t0 = time.monotonic()
        self._csv_path = path
        self._update_record_label()

    def _csv_append(self, raw: float):
        if self._csv_writer is None:
            if not self._record_chk.isChecked():
                return
            self._csv_start()
            if self._csv_writer is None:
                return
        t = time.monotonic() - self._csv_t0
        self._csv_writer.writerow([
            datetime.now().isoformat(timespec="milliseconds"),
            "%.3f" % t,
            "%.4f" % raw,
        ])
        self._csv_rows += 1
        if self._csv_rows % CSV_FLUSH_ROWS == 0:
            self._csv_flush()
            self._update_record_label()

    def _csv_flush(self):
        if self._csv_file is not None:
            try:
                self._csv_file.flush()
            except OSError:
                pass

    def _csv_stop(self):
        self._csv_flush()
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except OSError:
                pass
        self._csv_file = None
        self._csv_writer = None

    def _update_record_label(self):
        if self._csv_path and self._csv_rows:
            self._record_label.setText("%s (%d %s)" % (
                os.path.basename(self._csv_path), self._csv_rows, _("Keli.Rows")))
        elif self._csv_path:
            self._record_label.setText(os.path.basename(self._csv_path))
        else:
            self._record_label.setText(_("Keli.NoFile"))

    def _on_open_csv(self):
        if not self._csv_path or not os.path.exists(self._csv_path):
            self._ctx.status_message(_("Keli.Err.OpenCsv"), 3000)
            return
        self._csv_flush()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._csv_path))

    # ── 波形 ──
    def _on_pause_toggled(self, checked: bool):
        self._scope.set_paused(bool(checked))
        self._pause_btn.setText(_("Keli.Resume") if checked else _("Keli.Pause"))

    def _on_scope_clear(self):
        self._scope.clear()

    # ── 定时 ──
    def _on_stale_tick(self):
        self._update_status()
        self._update_diag()
        self._csv_flush()
        self._check_link()

    def _check_link(self):
        """链路看门狗：开流期间超过阈值没有任何回帧 → 判定掉线并开始探测。"""
        if not self._ctx.is_connected():
            return
        if not (self._want_stream or self._streaming):
            return
        if not self._link_up:
            return
        ref = self._last_rx or self._stream_since
        if not ref:
            return
        stale_s = max(PROBE_GRACE_S,
                      5.0 * max(1, int(self._interval_spin.value())) / 1000.0)
        if time.monotonic() - ref > stale_s:
            self._mark_link_down()

    # ── 生命周期 ──
    def on_activated(self):
        self._stale_timer.start()
        self._scope.start()
        self._update_buttons()
        self._update_status()

    def on_deactivating(self):
        self._stop_stream(send=True)
        self._stale_timer.stop()
        self._scope.stop()
        self._ack_timer.stop()
        self._query_timer.stop()
        self._version_timer.stop()
        self._restart_timer.stop()
        self._pending = None
        self._csv_stop()
        self._update_record_label()

    def on_connect(self):
        self._streaming = False
        self._pending = None
        self._last_raw = None
        self._last_rx = 0.0
        self._invalid = 0
        self._query_queue = []
        self._query_stage = 0
        self._resume_after_query = False
        self._rx_count = 0
        self._last_frame_hex = ""
        self._last_frame_kind = ""
        self._other_addrs = {}
        self._unparsed_logged = 0
        self._first_value_logged = False
        self._autostart_pending = False
        self._link_up = False
        self._want_stream = self._auto_start_chk.isChecked()
        self._stream_since = 0.0
        self._probe_timer.stop()
        self._ack_timer.stop()
        self._restart_timer.stop()
        self._start_timer.stop()
        self._query_timer.stop()
        self._version_timer.stop()
        self._update_value()
        self._update_diag()
        self._update_buttons()
        self._update_status()
        self._stale_timer.start()
        self._scope.start()

        if self._ctx.is_fd_mode() or self._ctx.get_bitrate() != 1_000_000:
            self._ctx.status_message(_("Keli.Hint.Bus"), 5000)
        if self._auto_start_chk.isChecked():
            # 先查询版本/间隔/地址（查询期间不处于连续流），随后才开始采集
            self._query_with_pause([P.build_query_version(self._addr()),
                                    P.build_query_interval(self._addr()),
                                    P.build_query_addr(self._addr())],
                                   autostart=True)

    def on_disconnect(self):
        self._stop_stream(send=False)
        self._stale_timer.stop()
        self._ack_timer.stop()
        self._query_timer.stop()
        self._version_timer.stop()
        self._restart_timer.stop()
        self._pending = None
        self._apply_busy(False)
        self._csv_stop()
        self._update_record_label()
        self._update_buttons()
        self._update_status()

    def confirm_close(self) -> bool:
        if self._csv_writer is not None:
            ret = QMessageBox.warning(
                self, _(("Keli.Record")), _("Keli.RecordCloseConfirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            return ret == QMessageBox.StandardButton.Yes
        return True

    def refresh_language(self):
        for box, key in self._titles:
            box.setTitle(_(key))
        for widget, key in self._static:
            if hasattr(widget, "setText"):
                widget.setText(_(key))
        self._pause_btn.setText(
            _("Keli.Resume") if self._scope.is_paused() else _("Keli.Pause"))
        self._scope.set_no_data_text(_("Keli.ScopeNoData"))
        self._update_status()
        self._update_record_label()
