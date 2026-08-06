"""主电源板监控 UI 面板。

布局：
    ┌─────────────────────────────────────────────┐
    │ 数据请求  (反馈复选框 / 请求间隔 / 持续请求 / 请求一次)│
    ├─────────────────────────────────────────────┤
    │ 状态行  (已连接·更新于 HH:MM:SS / 离线 / 未连接)│
    ├─────────────────────────────────────────────┤
    │ 监控表格  [参数(字段名)|描述(协议说明)|值|单位|状态]│
    └─────────────────────────────────────────────┘

接收主线程派发的批量帧（100ms），解码更新 PowerState，仅对变更单元格
增量刷新（compare-and-set），避免 10Hz 重绘闪烁。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout,
                                QLabel, QPushButton, QSpinBox, QTableWidget,
                                QTableWidgetItem, QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style
from . import protocol as P

logger = logging.getLogger("plugin.power_monitor")

# 颜色（复用 style.py 常量，不硬编码 hex）
_OK = style.LOAD_LOW    # 绿
_WARN = style.LOAD_MID  # 橙
_ERR = style.LOAD_HIGH  # 红
_DIM = style.FG_DIM
_TEXT = style.FG_TEXT

# 表格列
COL_PARAM = 0    # 参数（协议字段名，如 total_ov）
COL_DESC = 1     # 描述（协议文档"说明"列）
COL_VALUE = 2
COL_UNIT = 3
COL_STATUS = 4

# ── i18n keys（plugin.init() 注册）──
_I18N_KEYS = {
    "Power.Title":            ("主电源板监控",           "Power Board Monitor"),
    "Power.Control":          ("数据请求",               "Data Request"),
    "Power.AutoRequest":      ("持续请求",               "Continuous Request"),
    "Power.RequestOnce":      ("请求一次",               "Request Once"),
    "Power.ReqInterval":      ("请求间隔",               "Request Interval"),
    "Power.NotConnected":     ("CAN 未连接，请先在主界面连接设备",
                               "CAN not connected. Connect a device first."),
    "Power.Status.Connected": ("已连接",                 "Connected"),
    "Power.Status.Disconnected": ("未连接",              "Not Connected"),
    "Power.Status.Offline":   ("离线（无数据）",          "Offline (no data)"),
    "Power.Status.Waiting":   ("等待数据…",              "Waiting for data…"),
    "Power.Status.Updating":  ("更新于",                 "Updated at"),

    "Power.Col.Param":        ("参数",                   "Parameter"),
    "Power.Col.Desc":         ("描述",                   "Description"),
    "Power.Col.Value":        ("值",                     "Value"),
    "Power.Col.Unit":         ("单位",                   "Unit"),
    "Power.Col.Status":       ("状态/备注",               "Status / Note"),

    "Power.Sec.System":       ("系统状态",               "System Status"),
    "Power.Sec.Rails":        ("电源轨",                 "Power Rails"),
    "Power.Sec.Bat1":         ("电池1",                  "Battery 1"),
    "Power.Sec.Bat2":         ("电池2",                  "Battery 2"),

    "Power.OK":               ("正常",                   "Normal"),
    "Power.Abnormal":         ("异常",                   "Fault"),
    "Power.Online":           ("在线",                   "Online"),
    "Power.Offline":          ("离线",                   "Offline"),
    "Power.Pressed":          ("按下",                   "Pressed"),
    "Power.Released":         ("释放",                   "Released"),
    "Power.On":               ("开",                     "On"),
    "Power.Off":              ("关",                     "Off"),
    "Power.Charging":         ("充电中",                 "Charging"),
    "Power.Discharging":      ("放电中",                 "Discharging"),
    "Power.NoFault":          ("无故障",                 "No Fault"),
    "Power.NoData":           ("—",                      "—"),
    "Power.Unit.Cycle":       ("次",                     "cycles"),
    "Power.FaultLevel.Normal":("正常",                   "Normal"),
    "Power.FaultLevel.Minor": ("轻微",                   "Minor"),
    "Power.FaultLevel.Serious":("严重",                  "Serious"),
    "Power.FaultLevel.Fatal": ("致命",                   "Fatal"),

    "Power.Feed.Base":        ("基础（容量/循环/充电）",  "Base (cap/cycle/charging)"),
    "Power.Feed.Voltage":     ("电压电流",               "Voltage/Current"),
    "Power.Feed.Version":     ("版本",                   "Version"),
    "Power.Feed.Fault":       ("故障码",                 "Fault Codes"),
    "Power.Feed.Level":       ("等级/预警/温度",          "Level/Warnings/Temp"),
}

# 行"描述"列文案（协议文档"说明"列）。Bat.* 含 {n} 占位符（1/2）
DESC_I18N = {
    "Sys.StopKey":     ("急停：0=释放, 1=按下",          "E-stop: 0=released, 1=pressed"),
    "Sys.BatteryKey":  ("电池开关：0=关, 1=开",          "Battery switch: 0=off, 1=on"),
    "Sys.Charging":    ("充电（任一电池）：0=放电, 1=充电",
                        "Charging (either battery): 0=discharge, 1=charge"),
    "Sys.BatTempErr":  ("电池温度异常",                  "Battery temp error"),
    "Sys.DevSlaver":   ("副电源管理控制板在线",           "Slave power board online"),
    "Sys.DevDual":     ("双电池控制板在线",               "Dual-battery board online"),
    "Sys.Bat1Online":  ("电池1 在线",                    "Battery 1 online"),
    "Sys.Bat2Online":  ("电池2 在线",                    "Battery 2 online"),
    "Bat.Soc":         ("电池{n} SOC（0-100%）",          "Battery {n} SOC (0-100%)"),
    "Bat.Voltage":     ("电池{n} 电压（0.1V）",           "Battery {n} voltage (0.1V)"),
    "Bat.Current":     ("电池{n} 电流（0.1A，正=放电）",
                        "Battery {n} current (0.1A, + = discharge)"),
    "Bat.Temp":        ("电池{n} 电芯温度（°C）",         "Battery {n} cell temp (°C)"),
    "Bat.Capacity":    ("电池{n} 设计容量（÷256 mAh）",
                        "Battery {n} design capacity (÷256 mAh)"),
    "Bat.Cycle":       ("电池{n} 循环次数",              "Battery {n} cycle count"),
    "Bat.HwVer":       ("电池{n} 硬件版本",              "Battery {n} HW version"),
    "Bat.SwVer":       ("电池{n} 软件版本",              "Battery {n} SW version"),
    "Bat.Charging":    ("电池{n} 充电标志",              "Battery {n} charging flag"),
    "Bat.FaultLevel":  ("电池{n} 严重等级（0=正常,1=轻微,2=严重,3=致命）",
                        "Battery {n} fault level (0=normal,1=minor,2=serious,3=fatal)"),
    "Bat.Warnings":    ("电池{n} 其他预警位掩码",         "Battery {n} warnings mask"),
    "Bat.Faults":      ("电池{n} 详细故障",              "Battery {n} detailed faults"),
}

# 电源轨"描述"文案（字段名 → 协议说明）
RAIL_DESC = {
    "err_vin":         ("主输入电压异常 (48V)",          "Main input voltage fault (48V)"),
    "err_vin_dcdc":    ("DCDC 输出异常",                 "DCDC output fault"),
    "err_12v_int":     ("内部 12V 异常",                 "Internal 12V fault"),
    "err_5v_int":      ("内部 5V 异常",                  "Internal 5V fault"),
    "err_12v_ext":     ("外部 12V 异常",                 "External 12V fault"),
    "err_24v_ext":     ("外部 24V 异常",                 "External 24V fault"),
    "err_12v_user":    ("用户 12V 异常",                 "User 12V fault"),
    "err_24v_user":    ("用户 24V 异常",                 "User 24V fault"),
    "err_24v_comp":    ("工控机 24V 异常",               "Industrial-PC 24V fault"),
    "err_power":       ("从板电源异常",                  "Slave power fault"),
    "err_motor":       ("电机电源异常",                  "Motor power fault"),
    "err_chg_out":     ("预充电异常",                    "Pre-charge fault"),
    "err_hsd1_12v":    ("HSD1 12V 异常",                 "HSD1 12V fault"),
    "err_hsd2_12v":    ("HSD2 12V 异常",                 "HSD2 12V fault"),
    "err_hsd3_12v":    ("HSD3 12V 异常",                 "HSD3 12V fault"),
    "err_dbr":         ("制动电阻异常",                  "Brake resistor fault"),
    "err_hsd1_24v":    ("HSD1 24V 异常",                 "HSD1 24V fault"),
    "err_hsd2_24v":    ("HSD2 24V 异常",                 "HSD2 24V fault"),
    "err_hsd3_24v":    ("HSD3 24V 异常",                 "HSD3 24V fault"),
    "err_lsd1_24v":    ("LSD1 24V 异常",                 "LSD1 24V fault"),
    "err_lsd2_24v":    ("LSD2 24V 异常",                 "LSD2 24V fault"),
    "err_fan0":        ("风扇0 异常",                    "Fan 0 fault"),
    "err_fan1":        ("风扇1 异常",                    "Fan 1 fault"),
    "a_in1_io":        ("A_IN1_IO 模拟输入",             "A_IN1_IO analog input"),
    "a_in2_io":        ("A_IN2_IO 模拟输入",             "A_IN2_IO analog input"),
    "a_in3_io":        ("A_IN3_IO 模拟输入",             "A_IN3_IO analog input"),
    "seq_vin_fault":   ("VIN_DCDC 上电故障",             "VIN_DCDC power-up fault"),
    "seq_chg_fault":   ("预充电时序故障",                "Pre-charge sequence fault"),
    "seq_motor_fault": ("电机上电故障",                  "Motor power-up fault"),
    "err_ntc":         ("8路 NTC 温度异常",              "8-way NTC temperature fault"),
}

# 故障名（字段名 → i18n 文本，用于故障 tooltip）
FAULT_I18N = {
    "cell_ov":           ("电芯过压",           "Cell Over-voltage"),
    "total_ov":          ("总压过压",           "Total Over-voltage"),
    "fully_charged":     ("充满保护",           "Fully Charged"),
    "cell_uv":           ("电芯欠压",           "Cell Under-voltage"),
    "total_uv":          ("总压欠压",           "Total Under-voltage"),
    "short_circuit":     ("短路",               "Short Circuit"),
    "dischg_oc":         ("放电过流",           "Discharge Over-current"),
    "chg_oc":            ("充电过流",           "Charge Over-current"),
    "chg_ov_temp":       ("充电高温",           "Charge Over-temp"),
    "dischg_ov_temp":    ("放电高温",           "Discharge Over-temp"),
    "mos_ov_temp":       ("MOS 过温",           "MOS Over-temp"),
    "amb_ov_temp":       ("环境高温",           "Ambient Over-temp"),
    "amb_low_temp":      ("环境低温",           "Ambient Under-temp"),
    "temp_sensor_fail":  ("温度采集失效",       "Temp Sensor Fault"),
    "volt_sensor_fail":  ("电压采集失效",       "Voltage Sensor Fault"),
    "dischg_mos_fail":   ("放电 MOS 失效",     "Discharge MOS Fault"),
    "chg_mos_fail":      ("充电 MOS 失效",     "Charge MOS Fault"),
    "cell_imbalance":    ("电芯不均衡",         "Cell Imbalance"),
    "chg_temp_prot":     ("充电温度保护",       "Charge Temp Protection"),
    "dischg_temp_prot":  ("放电温度保护",       "Discharge Temp Protection"),
    "chg_temp_warn":     ("充电温度告警",       "Charge Temp Warning"),
    "dischg_temp_warn":  ("放电温度告警",       "Discharge Temp Warning"),
    "chg_ov_prot":       ("充电过压保护",       "Charge OVP"),
    "chg_ov_hw":         ("充电过压（硬件）",   "Charge OVP (HW)"),
    "chg_ov_second":     ("充电过压二次保护",   "Charge OVP Secondary"),
    "dischg_uv_prot":    ("放电欠压保护",       "Discharge UVP"),
    "dischg_uv_hw":      ("放电欠压（硬件）",   "Discharge UVP (HW)"),
    "chg_oc_prot":       ("充电过流保护",       "Charge OCP"),
    "dischg_oc_prot":    ("放电过流保护",       "Discharge OCP"),
    "dischg_oc_second":  ("放电过流二次保护",   "Discharge OCP Secondary"),
    "dischg_oc_hw":      ("放电过流（硬件）",   "Discharge OCP (HW)"),
    "hw_defected":       ("硬件损坏",           "Hardware Defect"),
    "chg_ov_warn":       ("充电过压告警",       "Charge OV Warning"),
    "dischg_uv_warn":    ("放电欠压告警",       "Discharge UV Warning"),
    "chg_oc_warn":       ("充电过流告警",       "Charge OC Warning"),
    "dischg_oc_warn":    ("放电过流告警",       "Discharge OC Warning"),
    "chg_fet_fail":      ("充电 FET 失效",     "Charge FET Fault"),
    "dischg_fet_fail":   ("放电 FET 失效",     "Discharge FET Fault"),
    "fuse_blown":        ("保险丝熔断",         "Fuse Blown"),
}

# 反馈复选框（bit, 帧ID, 标签 key）
_FEED_ITEMS = [
    (0, P.BASE_ID,       "Power.Feed.Base"),
    (1, P.VOLT_CURR_ID,  "Power.Feed.Voltage"),
    (2, P.VERSION_ID,    "Power.Feed.Version"),
    (3, P.ERROR_ID,      "Power.Feed.Fault"),
    (4, P.LEVEL_ID,      "Power.Feed.Level"),
]

# 电池行字段：(compute_field, 字段名模板(含{n}), 描述 key(含{n}))
_BAT_FIELDS = [
    ("Soc", "bat{n}_soc", "Power.Desc.Bat.Soc"),
    ("Voltage", "bat{n}_voltage", "Power.Desc.Bat.Voltage"),
    ("Current", "bat{n}_current", "Power.Desc.Bat.Current"),
    ("Temp", "bat{n}_temp", "Power.Desc.Bat.Temp"),
    ("Capacity", "bat{n}_capacity", "Power.Desc.Bat.Capacity"),
    ("Cycle", "bat{n}_cycle", "Power.Desc.Bat.Cycle"),
    ("HwVer", "bat{n}_hw_version", "Power.Desc.Bat.HwVer"),
    ("SwVer", "bat{n}_sw_version", "Power.Desc.Bat.SwVer"),
    ("Charging", "bat{n}_charging", "Power.Desc.Bat.Charging"),
    ("FaultLevel", "bat{n}_fault_level", "Power.Desc.Bat.FaultLevel"),
    ("Warnings", "bat{n}_warnings", "Power.Desc.Bat.Warnings"),
    ("FaultList", "bat{n}_faults", "Power.Desc.Bat.Faults"),
]


def _build_row_spec():
    """行规格：(row_id, 参数(字段名), 描述 key, compute_field)。段头为第 2/3 项占位。"""
    sys_rows = [
        ("sys.stopkey",  "stop_key_state",       "Power.Desc.Sys.StopKey",   "stop_key_state"),
        ("sys.batkey",   "battery_key_state",    "Power.Desc.Sys.BatteryKey", "battery_key_state"),
        ("sys.charging", "battery_charging",     "Power.Desc.Sys.Charging",  "battery_charging"),
        ("sys.battempe", "battery_temp_error",   "Power.Desc.Sys.BatTempErr", "battery_temp_error"),
        ("sys.slaver",   "device_online_slaver", "Power.Desc.Sys.DevSlaver", "device_online_slaver"),
        ("sys.dual",     "device_online_dual",   "Power.Desc.Sys.DevDual",   "device_online_dual"),
        ("sys.bat1on",   "device_online_bat1",   "Power.Desc.Sys.Bat1Online", "device_online_bat1"),
        ("sys.bat2on",   "device_online_bat2",   "Power.Desc.Sys.Bat2Online", "device_online_bat2"),
    ]
    rail_rows = [("rail." + name, name, f"Power.Desc.Rail.{name}", name)
                 for _, _, name in P.RAIL_BITS]
    rail_rows.append(("rail.err_ntc", "err_ntc", "Power.Desc.Rail.err_ntc", "err_ntc"))
    bat1_rows = [(f"bat1.{f}", fname.format(n=1), dkey, f) for f, fname, dkey in _BAT_FIELDS]
    bat2_rows = [(f"bat2.{f}", fname.format(n=2), dkey, f) for f, fname, dkey in _BAT_FIELDS]
    return ([("sec.sys", "", "Power.Sec.System", None)] + sys_rows
            + [("sec.rail", "", "Power.Sec.Rails", None)] + rail_rows
            + [("sec.bat1", "", "Power.Sec.Bat1", None)] + bat1_rows
            + [("sec.bat2", "", "Power.Sec.Bat2", None)] + bat2_rows)


_ROW_SPEC = _build_row_spec()
_ROW_FIELD = {rid: field for rid, field, _d, _cf in _ROW_SPEC}
_ROW_DESC_KEY = {rid: desc for rid, _f, desc, _cf in _ROW_SPEC}

# 帧 ID -> 受影响的行 id
_FRAME_ROWS = {
    P.SYS_ID: ([rid for rid, _f, _d, _cf in _ROW_SPEC
                if rid.startswith("sys.") or rid.startswith("rail.")]
               + ["bat1.Soc", "bat2.Soc"]),
    P.BASE_ID: ["bat1.Capacity", "bat2.Capacity", "bat1.Cycle", "bat2.Cycle",
                "bat1.Charging", "bat2.Charging"],
    P.VOLT_CURR_ID: ["bat1.Voltage", "bat2.Voltage", "bat1.Current", "bat2.Current"],
    P.VERSION_ID: ["bat1.HwVer", "bat2.HwVer", "bat1.SwVer", "bat2.SwVer"],
    P.ERROR_ID: ["bat1.FaultList", "bat2.FaultList"],
    P.LEVEL_ID: ["bat1.FaultLevel", "bat2.FaultLevel",
                 "bat1.Warnings", "bat2.Warnings", "bat1.Temp", "bat2.Temp"],
}


class _ConfigStore:
    PLUGIN_NAME = "power_monitor"
    DEFAULTS = {
        "feedback_mask": P.ALL_FEEDBACK_MASK,
        "auto_request": True,
        "req_interval": 1000,   # ms，持续请求的发送间隔
    }

    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        v = self._ctx.get_setting(f"{self.PLUGIN_NAME}.{key}", default)
        if isinstance(default, int) and isinstance(v, (int, float)):
            return int(v)
        if isinstance(default, bool) and isinstance(v, (int, bool)):
            return bool(v)
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


class PowerMonitorPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)
        self._state = P.PowerState()
        self._cell_cache: dict = {}
        self._row_index: dict = {}
        self._feed_checks: list = []   # (QCheckBox, label_key, bit)
        self._stale_threshold = 2.0    # 秒

        self._build_ui()
        self._load_config_to_ui()

        self._req_timer = QTimer(self)
        self._req_timer.setInterval(int(self._cfg.get("req_interval")))
        self._req_timer.timeout.connect(self._on_tick)
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._update_status_label)

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 数据请求区
        self._ctl_box = QGroupBox(_("Power.Control"))
        ctl_v = QVBoxLayout(self._ctl_box)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (bit, _fid, key) in enumerate(_FEED_ITEMS):
            chk = QCheckBox(_(key))
            chk.stateChanged.connect(self._on_feed_changed)
            grid.addWidget(chk, i // 4, i % 4)
            self._feed_checks.append((chk, key, bit))
        ctl_v.addLayout(grid)
        ctl_row = QHBoxLayout()
        self._lbl_req_interval = QLabel(_("Power.ReqInterval"))
        ctl_row.addWidget(self._lbl_req_interval)
        self._req_spin = QSpinBox()
        self._req_spin.setRange(100, 10000)
        self._req_spin.setSingleStep(100)
        self._req_spin.setSuffix(" ms")
        self._req_spin.setValue(1000)
        self._req_spin.valueChanged.connect(self._on_req_interval_changed)
        ctl_row.addWidget(self._req_spin)
        ctl_row.addSpacing(12)
        self._auto_chk = QCheckBox(_("Power.AutoRequest"))
        self._auto_chk.toggled.connect(self._on_auto_toggled)
        ctl_row.addWidget(self._auto_chk)
        ctl_row.addStretch(1)
        self._once_btn = QPushButton(_("Power.RequestOnce"))
        self._once_btn.setObjectName("primaryBtn")
        self._once_btn.clicked.connect(self._send_request)
        ctl_row.addWidget(self._once_btn)
        ctl_v.addLayout(ctl_row)
        root.addWidget(self._ctl_box)

        # 状态行
        status_row = QHBoxLayout()
        self._status_label = QLabel(_("Power.Status.Waiting"))
        self._status_label.setStyleSheet(f"color: {_DIM};")
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # 监控表格
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [_("Power.Col.Param"), _("Power.Col.Desc"), _("Power.Col.Value"),
             _("Power.Col.Unit"), _("Power.Col.Status")])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(COL_PARAM, 170)
        self._table.setColumnWidth(COL_DESC, 220)
        self._table.setColumnWidth(COL_VALUE, 90)
        self._table.setColumnWidth(COL_UNIT, 56)
        self._build_rows()
        root.addWidget(self._table, 1)

    def _row_desc(self, desc_key: str, rid: str) -> str:
        n = 1 if rid.startswith("bat1.") else (2 if rid.startswith("bat2.") else None)
        text = _(desc_key)
        if n:
            try:
                text = text.format(n=n)
            except Exception:
                pass
        return text

    def _build_rows(self):
        table = self._table
        for rid, field_name, desc_key, _compute_field in _ROW_SPEC:
            row = table.rowCount()
            table.insertRow(row)
            if rid.startswith("sec."):
                item = QTableWidgetItem(_(desc_key))
                font = QFont()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QBrush(QColor(_DIM)))
                bg = QColor(_DIM)
                bg.setAlpha(26)
                item.setBackground(QBrush(bg))
                item.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, COL_PARAM, item)
                table.setSpan(row, COL_PARAM, 1, 5)
            else:
                p = QTableWidgetItem(field_name)
                p.setToolTip(field_name)
                d = QTableWidgetItem(self._row_desc(desc_key, rid))
                v = QTableWidgetItem(_("Power.NoData"))
                u = QTableWidgetItem("")
                s = QTableWidgetItem("")
                for it in (v, u, s):
                    it.setForeground(QBrush(QColor(_DIM)))
                table.setItem(row, COL_PARAM, p)
                table.setItem(row, COL_DESC, d)
                table.setItem(row, COL_VALUE, v)
                table.setItem(row, COL_UNIT, u)
                table.setItem(row, COL_STATUS, s)
            self._row_index[rid] = row

    def _load_config_to_ui(self):
        mask = int(self._cfg.get("feedback_mask"))
        for chk, _key, bit in self._feed_checks:
            chk.blockSignals(True)
            chk.setChecked(bool(mask & (1 << bit)))
            chk.blockSignals(False)
        self._auto_chk.blockSignals(True)
        self._auto_chk.setChecked(bool(self._cfg.get("auto_request")))
        self._auto_chk.blockSignals(False)
        self._req_spin.blockSignals(True)
        self._req_spin.setValue(int(self._cfg.get("req_interval")))
        self._req_spin.blockSignals(False)

    # ── 配置 ──
    def _current_mask(self) -> int:
        mask = 0
        for chk, _key, bit in self._feed_checks:
            if chk.isChecked():
                mask |= (1 << bit)
        return mask

    def _on_feed_changed(self):
        mask = self._current_mask()
        self._cfg.set("feedback_mask", mask)
        if self._auto_chk.isChecked() and self._ctx.is_connected():
            self._send_request()

    def _on_auto_toggled(self, checked: bool):
        self._cfg.set("auto_request", bool(checked))
        if checked and self._ctx.is_connected():
            self._send_request()

    def _on_req_interval_changed(self, value: int):
        self._cfg.set("req_interval", value)
        self._req_timer.setInterval(value)
        if self._auto_chk.isChecked() and self._ctx.is_connected():
            self._send_request()

    def _send_request(self):
        if not self._ctx.is_connected():
            self._set_status(_("Power.NotConnected"), _ERR)
            return
        self._ctx.send_frame(P.build_request_frame(self._current_mask()))

    def _on_tick(self):
        if self._ctx.is_connected() and self._auto_chk.isChecked():
            self._send_request()

    # ── 状态标签 ──
    def _set_status(self, text: str, color: str):
        if (self._status_label.text() == text
                and color in self._status_label.styleSheet()):
            return
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color};")

    def _update_status_label(self):
        if not self._ctx.is_connected():
            self._set_status(_("Power.Status.Disconnected"), _DIM)
            return
        if self._state.last_rx:
            age = time.monotonic() - self._state.last_rx
            if age > self._stale_threshold:
                self._set_status(_("Power.Status.Offline"), _WARN)
            else:
                t = datetime.now().strftime("%H:%M:%S")
                self._set_status(
                    f"{_('Power.Status.Connected')} · {_('Power.Status.Updating')} {t}",
                    _OK)
        else:
            self._set_status(_("Power.Status.Waiting"), _DIM)

    # ── 帧处理 ──
    def _store(self, can_id: int, obj):
        st = self._state
        if can_id == P.SYS_ID:
            st.sys = obj
        elif can_id == P.BASE_ID:
            st.base = obj
        elif can_id == P.VOLT_CURR_ID:
            st.volt_curr = obj
        elif can_id == P.VERSION_ID:
            st.version = obj
        elif can_id == P.ERROR_ID:
            st.err = obj
        elif can_id == P.LEVEL_ID:
            st.level = obj

    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        seen = set()
        for f in frames:
            if f.is_tx or f.is_error or f.can_id not in P.DECODERS:
                continue
            try:
                obj = P.DECODERS[f.can_id](f.data)
            except Exception:
                logger.exception("解码帧失败 id=0x%X", f.can_id)
                continue
            if obj is None:
                continue
            self._store(f.can_id, obj)
            seen.add(f.can_id)
        if not seen:
            return
        self._state.last_rx = time.monotonic()
        self._update_status_label()
        for cid in seen:
            self._apply_rows(_FRAME_ROWS.get(cid, ()))

    def _apply_rows(self, row_ids):
        for rid in row_ids:
            cells = self._compute(rid)
            if self._cell_cache.get(rid) == cells:
                continue
            self._cell_cache[rid] = cells
            row = self._row_index.get(rid)
            if row is None:
                continue
            value, unit, status, vcolor, scolor = cells
            vi = self._table.item(row, COL_VALUE)
            vi.setText(value)
            vi.setForeground(QBrush(QColor(vcolor)))
            ui = self._table.item(row, COL_UNIT)
            ui.setText(unit)
            si = self._table.item(row, COL_STATUS)
            si.setText(status)
            si.setForeground(QBrush(QColor(scolor)))
            si.setToolTip(self._item_tooltip(rid, status))

    def _item_tooltip(self, rid: str, status: str) -> str:
        if rid.endswith("FaultList"):
            return self._fault_tooltip(rid)
        return status or ""

    def _fault_tooltip(self, rid: str) -> str:
        st = self._state
        n = 1 if rid.startswith("bat1.") else 2
        faults = self._attr(st.err, f"bat{n}_faults")
        if not faults:
            return ""
        return "\n".join(f"{fn}: {_('Power.Fault.' + fn)}" for fn in faults)

    # ── 值计算：返回 (value, unit, status, value_color, status_color) ──
    def _nodata(self):
        return (_("Power.NoData"), "", "", _DIM, _DIM)

    @staticmethod
    def _attr(obj, name, default=None):
        return getattr(obj, name, default) if obj is not None else default

    def _ok_err(self, ok: bool):
        return (_("Power.OK") if ok else _("Power.Abnormal"), "", "",
                _OK if ok else _ERR, _OK if ok else _ERR)

    def _online(self, v: bool):
        return (_("Power.Online") if v else _("Power.Offline"), "", "",
                _OK if v else _ERR, _OK if v else _ERR)

    def _compute(self, rid: str):
        st = self._state
        if rid.startswith("sys."):
            return self._compute_sys(rid, st.sys)
        if rid.startswith("rail."):
            return self._compute_rail(rid, st.sys)
        if rid.startswith("bat1."):
            return self._compute_bat(1, rid[5:], st)
        if rid.startswith("bat2."):
            return self._compute_bat(2, rid[5:], st)
        return self._nodata()

    def _compute_sys(self, rid: str, sys):
        if sys is None:
            return self._nodata()
        if rid == "sys.stopkey":
            v = sys.stop_key_state
            return (_("Power.Pressed") if v else _("Power.Released"), "", "",
                    _ERR if v else _OK, _ERR if v else _OK)
        if rid == "sys.batkey":
            v = sys.battery_key_state
            return (_("Power.On") if v else _("Power.Off"), "", "",
                    _OK if v else _DIM, _OK if v else _DIM)
        if rid == "sys.charging":
            v = sys.battery_charging
            return (_("Power.Charging") if v else _("Power.Discharging"), "", "",
                    _OK if v else _TEXT, _OK if v else _TEXT)
        if rid == "sys.battempe":
            return self._ok_err(not sys.battery_temp_error)
        if rid == "sys.slaver":
            return self._online(sys.device_online_slaver)
        if rid == "sys.dual":
            return self._online(sys.device_online_dual)
        if rid == "sys.bat1on":
            return self._online(sys.device_online_bat1)
        if rid == "sys.bat2on":
            return self._online(sys.device_online_bat2)
        return self._nodata()

    def _compute_rail(self, rid: str, sys):
        if sys is None:
            return self._nodata()
        name = rid[len("rail."):]
        if name == "err_ntc":
            bits = sys.ntc_bits
            if bits == 0:
                return (_("Power.OK"), "", "", _OK, _OK)
            lst = ",".join(f"NTC{i}" for i in range(8) if bits & (1 << i))
            return (lst, "", "", _ERR, _ERR)
        v = sys.rail_errors.get(name)
        if v is None:
            return self._nodata()
        if name.startswith("a_in"):
            return ("1" if v else "0", "", "", _TEXT, _TEXT)
        return self._ok_err(not v)

    def _compute_bat(self, n: int, field: str, st):
        if n == 1:
            soc = st.sys.bat1_soc if st.sys is not None else None
            volt = self._attr(st.volt_curr, "bat1_voltage")
            curr = self._attr(st.volt_curr, "bat1_current")
            temp = self._attr(st.level, "bat1_temp")
            cap = self._attr(st.base, "bat1_capacity")
            cyc = self._attr(st.base, "bat1_cycle")
            hw = self._attr(st.version, "bat1_hw")
            sw = self._attr(st.version, "bat1_sw")
            chg = self._attr(st.base, "bat1_charging")
            level = self._attr(st.level, "bat1_fault_level")
            warn = self._attr(st.level, "bat1_warnings")
            faults = self._attr(st.err, "bat1_faults")
        else:
            soc = st.sys.bat2_soc if st.sys is not None else None
            volt = self._attr(st.volt_curr, "bat2_voltage")
            curr = self._attr(st.volt_curr, "bat2_current")
            temp = self._attr(st.level, "bat2_temp")
            cap = self._attr(st.base, "bat2_capacity")
            cyc = self._attr(st.base, "bat2_cycle")
            hw = self._attr(st.version, "bat2_hw")
            sw = self._attr(st.version, "bat2_sw")
            chg = self._attr(st.base, "bat2_charging")
            level = self._attr(st.level, "bat2_fault_level")
            warn = self._attr(st.level, "bat2_warnings")
            faults = self._attr(st.err, "bat2_faults")

        if field == "Soc":
            if soc is None:
                return self._nodata()
            color = _ERR if soc < 20 else (_WARN if soc < 50 else _OK)
            return (f"{soc}", "%", "", color, color)
        if field == "Voltage":
            if volt is None:
                return self._nodata()
            return (f"{volt:.1f}", "V", "", _TEXT, _TEXT)
        if field == "Current":
            if curr is None:
                return self._nodata()
            s = _("Power.Discharging") if curr >= 0 else _("Power.Charging")
            c = _OK if curr >= 0 else _WARN
            return (f"{curr:+.1f}", "A", s, c, c)
        if field == "Temp":
            if temp is None:
                return self._nodata()
            return (f"{temp}", "°C", "", _TEXT, _TEXT)
        if field == "Capacity":
            if cap is None:
                return self._nodata()
            return (f"{cap}", "mAh", "", _TEXT, _TEXT)
        if field == "Cycle":
            if cyc is None:
                return self._nodata()
            return (f"{cyc}", _("Power.Unit.Cycle"), "", _TEXT, _TEXT)
        if field in ("HwVer", "SwVer"):
            v = hw if field == "HwVer" else sw
            if v is None:
                return self._nodata()
            return (f"{v >> 8}.{v & 0xFF}", "", "", _TEXT, _TEXT)
        if field == "Charging":
            if chg is None:
                return self._nodata()
            return (_("Power.Charging") if chg else _("Power.Discharging"),
                    "", "", _OK if chg else _TEXT, _OK if chg else _TEXT)
        if field == "FaultLevel":
            if level is None:
                return self._nodata()
            text = (_("Power.FaultLevel.Normal"), _("Power.FaultLevel.Minor"),
                    _("Power.FaultLevel.Serious"), _("Power.FaultLevel.Fatal"))
            colors = (_OK, _WARN, _ERR, _ERR)
            level = max(0, min(3, level))
            return (text[level], "", "", colors[level], colors[level])
        if field == "Warnings":
            if warn is None:
                return self._nodata()
            c = _OK if warn == 0 else _WARN
            s = _("Power.OK") if warn == 0 else _("Power.Abnormal")
            return (f"0x{warn:04X}", "", s, c, c)
        if field == "FaultList":
            if faults is None:
                return self._nodata()
            if not faults:
                return ("", "", _("Power.NoFault"), _OK, _OK)
            names = ", ".join(faults)   # 原始字段名，如 total_ov
            return ("", "", names, _ERR, _ERR)
        return self._nodata()

    # ── 生命周期 ──
    def on_activated(self):
        self._req_timer.start()
        self._stale_timer.start()

    def on_deactivating(self):
        self._req_timer.stop()
        self._stale_timer.stop()

    def on_connect(self):
        self._state = P.PowerState()
        self._cell_cache.clear()
        self._apply_rows([rid for rid in self._row_index
                          if not rid.startswith("sec.")])
        self._update_status_label()
        self._send_request()
        self._stale_timer.start()
        if self._auto_chk.isChecked():
            self._req_timer.start()

    def on_disconnect(self):
        self._req_timer.stop()
        self._stale_timer.stop()
        self._state = P.PowerState()
        self._update_status_label()

    def refresh_language(self):
        self._ctl_box.setTitle(_("Power.Control"))
        self._auto_chk.setText(_("Power.AutoRequest"))
        self._once_btn.setText(_("Power.RequestOnce"))
        self._lbl_req_interval.setText(_("Power.ReqInterval"))
        for chk, key, _bit in self._feed_checks:
            chk.setText(_(key))
        self._table.setHorizontalHeaderLabels(
            [_("Power.Col.Param"), _("Power.Col.Desc"), _("Power.Col.Value"),
             _("Power.Col.Unit"), _("Power.Col.Status")])
        for rid, row in self._row_index.items():
            field_name = _ROW_FIELD[rid]
            desc_key = _ROW_DESC_KEY[rid]
            item = self._table.item(row, COL_PARAM)
            if rid.startswith("sec."):
                item.setText(_(desc_key))
            else:
                item.setText(field_name)
                self._table.item(row, COL_DESC).setText(self._row_desc(desc_key, rid))
                self._cell_cache.pop(rid, None)
        self._apply_rows([rid for rid in self._row_index
                          if not rid.startswith("sec.")])
        self._update_status_label()
