"""捷电机 MIT 控制 UI 面板。"""
from __future__ import annotations

import csv
import logging
import math
import os
import random
import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                                QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                                QMessageBox, QPushButton, QScrollArea, QSlider,
                                QSpinBox, QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style
from cangui.plugin_ui import DisclosureSection, SectionPage, SectionTabs
from canable_sdk.frame import CANFrame

from . import protocol as P

class _WheelSpin:
    """Mixin: mouse wheel always adjusts the value by singleStep.

    Inside a scroll area an unfocused spin box would otherwise let the wheel
    scroll the panel instead of editing the field.
    """

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


logger = logging.getLogger("plugin.juxie_motor")


# 清除故障：以短促脉冲形式重复若干帧，确保控制器看到 0→1 跳变
CLEAR_BURST_FRAMES = 5
CLEAR_BURST_MS = 15
CLEAR_WATCH_MS = 1500

# SDO 序列逐帧间隔（6040h 使能序列 + 6060h 模式 + 6071h 目标）
SDO_STEP_MS = 40
# 序列发完后等待 6060h 读回的时限
SDO_READ_MS = 400
# 6060h 模式 → 反馈报文里的模式值（§2.2 Byte[14]）
SDO_MODE_FEEDBACK = {
    10: 5,      # CST/项目电流模式 → 反馈「电流环」
    5: 5,       # 项目原生电流模式
    7: 6,       # 力矩传感器闭环 → 反馈「力矩环」
}

# 往复记录 CSV 表头（每个上限保持中点记录一行）
WAVE_LOG_HEADER = ["cycle", "elapsed_s", "cmd_max_deg", "kp", "kd",
                   "primary_fb_deg", "mirror_fb_deg",
                   "primary_err_deg", "mirror_err_deg"]

# 随机往复：每周期在上限角内随机取幅值，下限为上限的该比例（避免幅度过小看不出运动）
WAVE_RAND_MIN_FRAC = 0.2

# 力矩满量程默认值（±30 Nm ↔ raw 0..4095）与合法下限
DEFAULT_TORQUE_MAX = 300.0
MIN_TORQUE_MAX = 1.0


def _base_dir() -> str:
    """可执行文件所在目录（打包后）或工程根目录（源码运行）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


class _ConfigStore:
    PLUGIN_NAME = "juxie_motor"
    DEFAULTS = {
        "dev_id": 1,
        "mirror": True,
        "mirror_id": 2,
        "target_max": 35.0,
        "enable": True,
        "brake": True,
        "auto_send": True,
        "auto_request": True,
        "req_interval": 100,
        "pos_max": 180.0,
        "vel_max": 3000.0,
        "torque_max": DEFAULT_TORQUE_MAX,
        "kp": 6.0,
        "kd": 0.1,
        "target_pos": 0,
        "target_vel": 0.0,
        "target_torque": 0.0,
        "tq_raw_enable": False,
        "tq_raw": 2048,
        "tq_zero_mode": "offset",
        "mit_continuous": False,
        "mit_interval": 20,
        "slew_dps": 60.0,
        "auto_clear": False,
        "clear_interval": 10,
        "wave_amp": 30.0,
        "wave_period": 3.0,
        "wave_hold_hi": 5.0,
        "wave_hold_lo": 5.0,
        "wave_interval": 10,
        "wave_log": True,
        "sdo_current_ma": 500,
        "sdo_torque_nm": 1.0,
        "sdo_mode": "current",
    }

    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        v = self._ctx.get_setting(f"{self.PLUGIN_NAME}.{key}", default)
        if isinstance(default, bool) and isinstance(v, (int, bool)):
            return bool(v)
        if isinstance(default, (int, float)) and isinstance(v, (int, float)):
            return type(default)(v)
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


class JuxieMotorPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)
        # 两台电机反馈：[0]=主电机, [1]=镜像电机
        self._fb: list = [None, None]
        self._last_rx: list = [0.0, 0.0]

        # 周期往复状态需在 _load_config() 之前就绪（_update_wave_info 会读取）
        self._wave_on = False
        self._wave_t0 = 0.0
        self._wave_rand = False          # 随机幅值模式
        self._wave_amp_cur = 0.0         # 本周期的实际幅值（随机模式下每周期重取）
        self._wave_cur_idx = -1
        self._wave_log_file = None
        self._wave_log_rows = 0
        self._wave_last_cycle = -1

        # 清除故障脉冲
        self._clear_burst_left = 0
        self._clear_pending = False

        # SDO 电流/力矩模式下发（逐帧间隔，避免驱动器来不及处理）
        self._sdo_queue: list = []
        self._sdo_what = ""
        self._sdo_expect_mode = 0
        self._sdo_retried = False
        self._sdo_retry_args = None

        self._build_ui()
        self._load_config()

        self._clear_burst_timer = QTimer(self)
        self._clear_burst_timer.setInterval(CLEAR_BURST_MS)
        self._clear_burst_timer.timeout.connect(self._send_clear_tick)
        self._clear_watch_timer = QTimer(self)
        self._clear_watch_timer.setSingleShot(True)
        self._clear_watch_timer.timeout.connect(self._on_clear_watch_timeout)

        # 定时请求反馈
        self._req_timer = QTimer(self)
        self._req_timer.setInterval(int(self._cfg.get("req_interval")))
        self._req_timer.timeout.connect(self._on_req_tick)

        # 连续 MIT 控制（位置斜坡限速，避免目标阶跃触发过载保护）
        self._slew_pos: float | None = None
        self._mit_timer = QTimer(self)
        self._mit_timer.setInterval(int(self._cfg.get("mit_interval")))
        self._mit_timer.timeout.connect(self._on_mit_tick)

        # 周期清错（清错脉冲 + 释放帧，保证每次都有 0→1 跳变）
        self._auto_clear_timer = QTimer(self)
        self._auto_clear_timer.setInterval(int(self._cfg.get("clear_interval")))
        self._auto_clear_timer.timeout.connect(self._on_auto_clear_tick)
        self._clear_release_timer = QTimer(self)
        self._clear_release_timer.setSingleShot(True)
        self._clear_release_timer.setInterval(CLEAR_BURST_MS)
        self._clear_release_timer.timeout.connect(self._on_clear_release)

        # 周期往复（0° ↔ 上限角）
        self._wave_timer = QTimer(self)
        self._wave_timer.setInterval(int(self._cfg.get("wave_interval")))
        self._wave_timer.timeout.connect(self._on_wave_tick)

        # SDO 序列发送
        self._sdo_timer = QTimer(self)
        self._sdo_timer.setSingleShot(True)
        self._sdo_timer.setInterval(SDO_STEP_MS)
        self._sdo_timer.timeout.connect(self._sdo_step)

        # 模式读回超时
        self._sdo_read_timer = QTimer(self)
        self._sdo_read_timer.setSingleShot(True)
        self._sdo_read_timer.setInterval(SDO_READ_MS)
        self._sdo_read_timer.timeout.connect(self._on_sdo_read_timeout)

    # ── UI 构建 ──

    def _build_ui(self):
        self._sections = []
        # 内容较多：放进滚动区，避免窗口偏小时目标设置等控件被裁剪到无法操作
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_dev_config())
        root.addWidget(self._build_feedback())
        self._detail_tabs = SectionTabs()
        for page in (self._build_mit_control(), self._build_sdo(), self._build_wave()):
            self._detail_tabs.add_section(page)
        root.addWidget(self._detail_tabs, 1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _section(self, key, page=False):
        box = SectionPage(_(key)) if page else QGroupBox(_(key))
        self._sections.append((box, key))
        return box

    def _unit_label(self, text: str, width: int = 46) -> QLabel:
        """Unit label shown beside a field, without reserving empty width."""
        lbl = QLabel(text)
        style.set_text_color(lbl, style.FG_DIM)
        lbl.setMaximumWidth(width)
        return lbl

    def _grid_label(self, key: str) -> QLabel:
        return QLabel(_(key))

    def _build_dev_config(self) -> QGroupBox:
        box = self._section("Juxie.DevConfig")
        g = QGridLayout(box)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)

        self._dev_id_label = QLabel(_("Juxie.DevID"))
        g.addWidget(self._dev_id_label, 0, 0)
        self._dev_id_spin = _IntSpin()
        self._dev_id_spin.setRange(0, 127)
        self._dev_id_spin.setValue(1)
        self._dev_id_spin.valueChanged.connect(self._on_dev_id_changed)
        g.addWidget(self._dev_id_spin, 0, 1)
        g.addWidget(self._unit_label(""), 0, 2)

        self._mirror_chk = QCheckBox(_("Juxie.Mirror"))
        self._mirror_chk.toggled.connect(self._on_mirror_changed)
        g.addWidget(self._mirror_chk, 0, 3)
        self._mirror_id_label = QLabel(_("Juxie.MirrorID"))
        g.addWidget(self._mirror_id_label, 0, 4)
        self._mirror_id_spin = _IntSpin()
        self._mirror_id_spin.setRange(0, 127)
        self._mirror_id_spin.setValue(2)
        self._mirror_id_spin.valueChanged.connect(self._on_mirror_id_changed)
        g.addWidget(self._mirror_id_spin, 0, 5)
        self._id_label = QLabel()
        style.set_text_color(self._id_label, style.FG_DIM)
        g.addWidget(self._id_label, 0, 6, 1, 2)

        self._target_max_label = QLabel(_("Juxie.TargetMax"))
        g.addWidget(self._target_max_label, 1, 0)
        self._target_max_spin = _FloatSpin()
        self._target_max_spin.setRange(0.1, 360.0)
        self._target_max_spin.setDecimals(1)
        self._target_max_spin.setSingleStep(1.0)
        self._target_max_spin.setValue(35.0)
        self._target_max_spin.valueChanged.connect(self._on_target_max_changed)
        g.addWidget(self._target_max_spin, 1, 1)
        g.addWidget(self._unit_label(_("Juxie.Unit.Deg")), 1, 2)

        self._auto_req_chk = QCheckBox(_("Juxie.AutoRequest"))
        self._auto_req_chk.toggled.connect(self._on_auto_req_changed)
        g.addWidget(self._auto_req_chk, 1, 3)
        self._req_label = QLabel(_("Juxie.ReqInterval"))
        g.addWidget(self._req_label, 1, 4)
        self._req_spin = _IntSpin()
        self._req_spin.setRange(10, 5000)
        self._req_spin.setSingleStep(10)
        self._req_spin.setValue(100)
        self._req_spin.valueChanged.connect(self._on_req_interval_changed)
        g.addWidget(self._req_spin, 1, 5)
        g.addWidget(self._unit_label(_("Juxie.Unit.Ms")), 1, 6)
        self._sync_btn = QPushButton(_("Juxie.RequestFeedback"))
        self._sync_btn.clicked.connect(self._on_request_feedback)
        g.addWidget(self._sync_btn, 1, 7)
        g.setColumnStretch(2, 1)
        return box

    def _build_mit_control(self) -> QWidget:
        box = self._section("Juxie.MITControl", page=True)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        tuning = DisclosureSection(_("Juxie.Tuning"))
        self._sections.append((tuning, "Juxie.Tuning"))
        tuning_grid = QGridLayout(tuning.body)
        tuning_grid.setColumnStretch(6, 1)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)

        # ---- scale limits: (label, spin, unit) x 2 per row ----
        tuning_grid.addWidget(self._grid_label("Juxie.PosMax"), 0, 0)
        self._pos_max_spin = _FloatSpin()
        self._pos_max_spin.setRange(1.0, 360.0)
        self._pos_max_spin.setDecimals(1)
        self._pos_max_spin.setSingleStep(1.0)
        self._pos_max_spin.setValue(180.0)
        self._pos_max_spin.valueChanged.connect(self._on_scale_changed)
        tuning_grid.addWidget(self._pos_max_spin, 0, 1)
        tuning_grid.addWidget(self._unit_label(_("Juxie.Unit.Deg")), 0, 2)

        tuning_grid.addWidget(self._grid_label("Juxie.VelMax"), 0, 3)
        self._vel_max_spin = _FloatSpin()
        self._vel_max_spin.setRange(1.0, 100000.0)
        self._vel_max_spin.setDecimals(0)
        self._vel_max_spin.setSingleStep(10.0)
        self._vel_max_spin.setValue(3000.0)
        self._vel_max_spin.valueChanged.connect(self._on_scale_changed)
        tuning_grid.addWidget(self._vel_max_spin, 0, 4)
        tuning_grid.addWidget(self._unit_label(_("Juxie.Unit.RPM")), 0, 5)

        tuning_grid.addWidget(self._grid_label("Juxie.TorqueMax"), 1, 0)
        self._torque_max_spin = _FloatSpin()
        self._torque_max_spin.setRange(MIN_TORQUE_MAX, 1000.0)
        self._torque_max_spin.setDecimals(1)
        self._torque_max_spin.setSingleStep(1.0)
        self._torque_max_spin.setValue(DEFAULT_TORQUE_MAX)
        self._torque_max_spin.valueChanged.connect(self._on_scale_changed)
        tuning_grid.addWidget(self._torque_max_spin, 1, 1)
        tuning_grid.addWidget(self._unit_label(_("Juxie.Unit.Nm")), 1, 2)

        g.addWidget(self._grid_label("Juxie.TargetVel"), 0, 0)
        self._vel_spin = _FloatSpin()
        self._vel_spin.setRange(-500.0, 500.0)
        self._vel_spin.setDecimals(1)
        self._vel_spin.setSingleStep(10.0)
        self._vel_spin.setValue(0.0)
        g.addWidget(self._vel_spin, 0, 1)
        g.addWidget(self._unit_label(_("Juxie.Unit.RPM")), 0, 2)

        tuning_grid.addWidget(self._grid_label("Juxie.Kp"), 2, 0)
        self._kp_spin = _FloatSpin()
        self._kp_spin.setRange(0.0, P.KP_MAX)
        self._kp_spin.setDecimals(1)
        self._kp_spin.setSingleStep(1.0)
        self._kp_spin.setValue(6.0)
        tuning_grid.addWidget(self._kp_spin, 2, 1)
        self._kp_unit = self._unit_label("", 70)
        tuning_grid.addWidget(self._kp_unit, 2, 2)

        tuning_grid.addWidget(self._grid_label("Juxie.Kd"), 2, 3)
        self._kd_spin = _FloatSpin()
        self._kd_spin.setRange(0.0, P.KD_MAX)
        self._kd_spin.setDecimals(2)
        self._kd_spin.setSingleStep(0.01)
        self._kd_spin.setValue(0.1)
        tuning_grid.addWidget(self._kd_spin, 2, 4)
        self._kd_unit = self._unit_label("", 70)
        tuning_grid.addWidget(self._kd_unit, 2, 5)

        # ---- feedforward torque: wheel step 0.1 Nm ----
        self._torque_label = QLabel(_("Juxie.TargetTorque"))
        g.addWidget(self._torque_label, 0, 3)
        self._torque_spin = _FloatSpin()
        self._torque_spin.setRange(-DEFAULT_TORQUE_MAX, DEFAULT_TORQUE_MAX)
        self._torque_spin.setDecimals(2)
        self._torque_spin.setSingleStep(0.1)
        self._torque_spin.setValue(0.0)
        g.addWidget(self._torque_spin, 0, 4)
        g.addWidget(self._unit_label(_("Juxie.Unit.Nm")), 0, 5)

        self._tq_raw_chk = QCheckBox(_("Juxie.TorqueRaw"))
        self._tq_raw_chk.setToolTip(_("Juxie.TorqueRawTip"))
        self._tq_raw_chk.toggled.connect(self._on_tq_raw_changed)
        tuning_grid.addWidget(self._tq_raw_chk, 1, 3)
        self._tq_raw_spin = _IntSpin()
        self._tq_raw_spin.setRange(0, 4095)
        self._tq_raw_spin.setValue(2048)
        self._tq_raw_spin.setToolTip(_("Juxie.TorqueRawTip"))
        self._tq_raw_spin.valueChanged.connect(self._on_tq_raw_changed)
        tuning_grid.addWidget(self._tq_raw_spin, 1, 4)
        tuning_grid.addWidget(self._unit_label(""), 1, 5)

        tuning_grid.addWidget(self._grid_label("Juxie.TorqueZero"), 3, 0)
        self._tq_zero_combo = QComboBox()
        self._tq_zero_combo.addItem(_("Juxie.TorqueZeroOffset"), "offset")
        self._tq_zero_combo.addItem(_("Juxie.TorqueZeroSigned"), "signed")
        self._tq_zero_combo.setToolTip(_("Juxie.TorqueZeroTip"))
        self._tq_zero_combo.currentIndexChanged.connect(self._on_tq_zero_changed)
        tuning_grid.addWidget(self._tq_zero_combo, 3, 1, 1, 5)

        for spin in (self._vel_spin, self._kp_spin, self._kd_spin,
                     self._torque_spin):
            spin.valueChanged.connect(self._on_target_params_changed)

        # ---- target position (widest row) ----
        g.addWidget(self._grid_label("Juxie.TargetPos"), 1, 0)
        self._pos_slider = QSlider(Qt.Horizontal)
        self._pos_slider.setRange(-1800, 1800)
        self._pos_slider.setSingleStep(5)
        self._pos_slider.setPageStep(50)
        self._pos_slider.setValue(0)
        self._pos_slider.valueChanged.connect(self._on_pos_changed)
        g.addWidget(self._pos_slider, 1, 1, 1, 3)
        self._pos_label = QLabel("+0.0" + _("Juxie.Unit.Deg"))
        self._pos_label.setFixedWidth(58)
        self._pos_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        style.set_text_color(self._pos_label, style.FG_DIM)
        g.addWidget(self._pos_label, 1, 4)
        self._mirror_target_label = QLabel("")
        self._mirror_target_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        style.set_text_color(self._mirror_target_label, style.FG_DIM)
        g.addWidget(self._mirror_target_label, 1, 5)
        g.setColumnStretch(6, 1)
        outer.addLayout(g)

        ctl_row = QHBoxLayout()
        self._enable_chk = QCheckBox(_("Juxie.Enable"))
        self._enable_chk.toggled.connect(self._on_ctl_changed)
        ctl_row.addWidget(self._enable_chk)
        self._brake_chk = QCheckBox(_("Juxie.Brake"))
        self._brake_chk.toggled.connect(self._on_ctl_changed)
        ctl_row.addWidget(self._brake_chk)
        self._clear_err_btn = QPushButton(_("Juxie.ClearError"))
        self._clear_err_btn.clicked.connect(self._on_clear_error)
        ctl_row.addWidget(self._clear_err_btn)
        self._zero_btn = QPushButton(_("Juxie.Zero"))
        self._zero_btn.clicked.connect(self._on_zero)
        ctl_row.addWidget(self._zero_btn)
        self._auto_send_chk = QCheckBox(_("Juxie.AutoSend"))
        self._auto_send_chk.setChecked(True)
        self._auto_send_chk.toggled.connect(self._on_auto_send_changed)
        ctl_row.addWidget(self._auto_send_chk)
        ctl_row.addStretch(1)
        outer.addLayout(ctl_row)

        cont_row = QHBoxLayout()
        self._mit_cont_chk = QCheckBox(_("Juxie.Continuous"))
        self._mit_cont_chk.toggled.connect(self._on_mit_cont_changed)
        cont_row.addWidget(self._mit_cont_chk)
        self._mit_int_label = QLabel(_("Juxie.MitInterval"))
        cont_row.addWidget(self._mit_int_label)
        self._mit_interval_spin = _IntSpin()
        self._mit_interval_spin.setRange(5, 200)
        self._mit_interval_spin.setSingleStep(5)
        self._mit_interval_spin.setValue(20)
        self._mit_interval_spin.valueChanged.connect(self._on_mit_interval_changed)
        cont_row.addWidget(self._mit_interval_spin)
        cont_row.addWidget(self._unit_label(_("Juxie.Unit.Ms")))
        self._slew_label = QLabel(_("Juxie.SlewRate"))
        cont_row.addWidget(self._slew_label)
        self._slew_spin = _FloatSpin()
        self._slew_spin.setRange(0.0, 720.0)
        self._slew_spin.setDecimals(0)
        self._slew_spin.setSingleStep(5.0)
        self._slew_spin.setValue(60.0)
        self._slew_spin.valueChanged.connect(self._on_slew_changed)
        cont_row.addWidget(self._slew_spin)
        cont_row.addWidget(self._unit_label(_("Juxie.Unit.DegS"), 54))
        cont_row.addStretch(1)
        outer.addLayout(cont_row)

        clear_row = QHBoxLayout()
        self._auto_clear_chk = QCheckBox(_("Juxie.AutoClear"))
        self._auto_clear_chk.toggled.connect(self._on_auto_clear_changed)
        clear_row.addWidget(self._auto_clear_chk)
        self._auto_clear_label = QLabel(_("Juxie.ClearInterval"))
        clear_row.addWidget(self._auto_clear_label)
        self._clear_interval_spin = _IntSpin()
        self._clear_interval_spin.setRange(1, 2147483647)
        self._clear_interval_spin.setSingleStep(1)
        self._clear_interval_spin.setValue(10)
        self._clear_interval_spin.valueChanged.connect(
            self._on_clear_interval_changed)
        clear_row.addWidget(self._clear_interval_spin)
        clear_row.addWidget(self._unit_label(_("Juxie.Unit.Ms")))
        clear_row.addStretch(1)
        outer.addLayout(clear_row)

        self._send_btn = QPushButton(_("Juxie.SendMIT"))
        self._send_btn.clicked.connect(self._on_send_mit)
        ctl_row.addWidget(self._send_btn)

        self._frame_label = QLabel("")
        style.set_text_color(self._frame_label, style.FG_DIM)
        self._frame_label.setToolTip(_("Juxie.FrameTip"))
        tuning_grid.addWidget(self._frame_label, 4, 0, 1, 7)
        outer.addStretch(1)
        outer.addWidget(tuning)
        return box

    # ── SDO 电流 / 力矩控制（文档 §4.3）──
    def _build_sdo(self) -> QWidget:
        box = self._section("Juxie.Sdo", page=True)
        lay = QVBoxLayout(box)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignTop)

        row = QHBoxLayout()
        self._sdo_cur_label = QLabel(_("Juxie.SdoCurrent"))
        row.addWidget(self._sdo_cur_label)
        self._sdo_current_spin = _IntSpin()
        self._sdo_current_spin.setRange(0, P.CURRENT_MAX_MA)
        self._sdo_current_spin.setSingleStep(50)
        self._sdo_current_spin.setValue(int(self._cfg.get("sdo_current_ma")))
        self._sdo_current_spin.setSuffix(" mA")
        self._sdo_current_spin.valueChanged.connect(self._on_sdo_current_changed)
        row.addWidget(self._sdo_current_spin)
        self._sdo_cur_btn = QPushButton(_("Juxie.SdoApplyCurrent"))
        self._sdo_cur_btn.clicked.connect(self._on_sdo_current)
        row.addWidget(self._sdo_cur_btn)

        row.addSpacing(14)
        self._sdo_tq_label = QLabel(_("Juxie.SdoTorque"))
        row.addWidget(self._sdo_tq_label)
        self._sdo_torque_spin = _FloatSpin()
        self._sdo_torque_spin.setRange(0.0, 6553.5)
        self._sdo_torque_spin.setDecimals(1)
        self._sdo_torque_spin.setSingleStep(0.1)
        self._sdo_torque_spin.setValue(float(self._cfg.get("sdo_torque_nm")))
        self._sdo_torque_spin.setSuffix(" N·m")
        self._sdo_torque_spin.valueChanged.connect(self._on_sdo_torque_changed)
        row.addWidget(self._sdo_torque_spin)
        self._sdo_tq_btn = QPushButton(_("Juxie.SdoApplyTorque"))
        self._sdo_tq_btn.clicked.connect(self._on_sdo_torque)
        row.addWidget(self._sdo_tq_btn)

        row.addStretch(1)
        self._sdo_zero_btn = QPushButton(_("Juxie.SdoZero"))
        self._sdo_zero_btn.clicked.connect(self._on_sdo_zero)
        row.addWidget(self._sdo_zero_btn)
        lay.addLayout(row)

        self._sdo_hint = QLabel(_("Juxie.SdoHint"))
        style.set_text_color(self._sdo_hint, style.FG_DIM)
        self._sdo_hint.setWordWrap(True)
        lay.addWidget(self._sdo_hint)

        self._sdo_status = QLabel(_("Juxie.SdoIdle"))
        style.set_text_color(self._sdo_status, style.FG_DIM)
        lay.addWidget(self._sdo_status)
        return box

    def _on_sdo_current_changed(self, value: int):
        self._cfg.set("sdo_current_ma", int(value))

    def _on_sdo_torque_changed(self, value: float):
        self._cfg.set("sdo_torque_nm", float(value))

    def _sdo_ready(self) -> bool:
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Juxie.Err.NotConnected"), 3000)
            return False
        if not self._ctx.is_fd_mode():
            self._ctx.status_message(_("Juxie.Err.NeedFd"), 3000)
            return False
        return True

    def _stop_mode_conflicts(self):
        """进入 SDO 电流/力矩模式前，停掉会改写运行模式的 MIT 连续下发。"""
        if self._mit_cont_chk.isChecked():
            self._mit_cont_chk.setChecked(False)
        if self._wave_on:
            self._stop_wave(send_zero=False)
        if self._auto_clear_chk.isChecked():
            self._auto_clear_chk.setChecked(False)

    def _start_sdo(self, frames, what: str, expect_mode: int = 0,
                   retry=None):
        if not self._sdo_ready():
            return
        self._stop_mode_conflicts()
        self._sdo_queue = list(frames)
        self._sdo_what = what
        self._sdo_expect_mode = int(expect_mode)
        self._sdo_retried = False
        self._sdo_retry_args = retry
        self._sdo_status.setText(_("Juxie.SdoSending").format(what=what))
        style.set_text_color(self._sdo_status, style.LOAD_MID)
        self._sdo_step()

    def _sdo_step(self):
        if not self._ctx.is_connected():
            self._sdo_queue = []
            return
        if not self._sdo_queue:
            self._sdo_finish()
            return
        frame = self._sdo_queue.pop(0)
        self._ctx.send_frame(frame)
        logger.info("SDO TX id=0x%03X %s", frame.can_id, frame.data.hex(" "))
        if self._sdo_queue:
            self._sdo_timer.start()

    def _sdo_finish(self):
        if not self._sdo_what:
            return
        if not self._sdo_expect_mode:
            self._sdo_status.setText(_("Juxie.SdoSent").format(what=self._sdo_what))
            style.set_text_color(self._sdo_status, style.LOAD_LOW)
            return
        # 序列发完：读回 6060h，确认驱动器真的切到了目标模式
        self._sdo_status.setText(_("Juxie.SdoVerify").format(what=self._sdo_what))
        style.set_text_color(self._sdo_status, style.LOAD_MID)
        self._ctx.send_frame(P.build_sdo_read(self._dev_id_spin.value(), P.OBJ_MODES))
        self._sdo_read_timer.start()

    def _sdo_success(self):
        self._sdo_read_timer.stop()
        mode = self._sdo_expect_mode
        self._sdo_expect_mode = 0
        self._sdo_retry_args = None
        self._sdo_status.setText(_("Juxie.SdoModeOk").format(mode=mode))
        style.set_text_color(self._sdo_status, style.LOAD_LOW)

    def _sdo_fail(self, key: str, **kw):
        if self._sdo_expect_mode and not self._sdo_retried and self._sdo_retry_args:
            mode, target = self._sdo_retry_args
            self._sdo_retried = True
            self._sdo_queue = P.build_mode_sequence_before_enable(
                self._dev_id_spin.value(), mode, target)
            self._sdo_status.setText(_("Juxie.SdoRetry"))
            style.set_text_color(self._sdo_status, style.LOAD_MID)
            logger.warning("SDO mode not applied (%s) -> retry mode-before-enable",
                           key)
            self._sdo_step()
            return
        self._sdo_read_timer.stop()
        self._sdo_expect_mode = 0
        self._sdo_retry_args = None
        self._sdo_status.setText(_(key).format(**kw))
        style.set_text_color(self._sdo_status, style.LOAD_HIGH)
        logger.warning("SDO mode verification failed: %s %s", key, kw)

    def _on_sdo_read_timeout(self):
        self._sdo_fail("Juxie.SdoNoReply")

    def _on_sdo_response(self, data):
        parsed = P.parse_sdo_response(data)
        if parsed is None:
            return
        index, value = parsed
        logger.info("SDO RX index=0x%04X value=%s", index, value)
        if index != P.OBJ_MODES or not self._sdo_expect_mode:
            return
        if value is None:
            self._sdo_fail("Juxie.SdoModeAbort")
        elif value == self._sdo_expect_mode:
            self._sdo_success()
        else:
            self._sdo_fail("Juxie.SdoModeMismatch", mode=value)

    def _on_sdo_current(self):
        ma = int(self._sdo_current_spin.value())
        self._cfg.set("sdo_current_ma", ma)
        self._cfg.set("sdo_mode", "current")
        self._start_sdo(
            P.build_current_mode_sequence(self._dev_id_spin.value(), ma),
            _("Juxie.SdoWhatCurrent").format(ma=ma),
            expect_mode=P.MODE_CST_PROJECT,
            retry=(P.MODE_CST_PROJECT, ma))

    def _on_sdo_torque(self):
        nm = float(self._sdo_torque_spin.value())
        self._cfg.set("sdo_torque_nm", nm)
        self._cfg.set("sdo_mode", "torque")
        raw = max(0, min(0xFFFF, int(round(nm / P.TORQUE_LSB_NM))))
        self._start_sdo(
            P.build_torque_mode_sequence(self._dev_id_spin.value(), nm),
            _("Juxie.SdoWhatTorque").format(nm=nm),
            expect_mode=P.MODE_TORQUE_SENSOR,
            retry=(P.MODE_TORQUE_SENSOR, raw))

    def _on_sdo_zero(self):
        self._start_sdo(
            [P.build_sdo_target(self._dev_id_spin.value(), 0)],
            _("Juxie.SdoWhatZero"))

    def _build_wave(self) -> QWidget:
        box = self._section("Juxie.Wave", page=True)
        outer = QVBoxLayout(box)
        outer.setAlignment(Qt.AlignTop)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)

        self._wave_amp_label = self._grid_label("Juxie.WaveAmp")
        g.addWidget(self._wave_amp_label, 0, 0)
        self._wave_amp_spin = _FloatSpin()
        self._wave_amp_spin.setRange(0.1, 360.0)
        self._wave_amp_spin.setDecimals(1)
        self._wave_amp_spin.setSingleStep(1.0)
        self._wave_amp_spin.setValue(30.0)
        self._wave_amp_spin.valueChanged.connect(self._on_wave_param_changed)
        g.addWidget(self._wave_amp_spin, 0, 1)
        g.addWidget(self._unit_label(_("Juxie.Unit.Deg")), 0, 2)

        self._wave_period_label = self._grid_label("Juxie.WavePeriod")
        g.addWidget(self._wave_period_label, 0, 3)
        self._wave_period_spin = _FloatSpin()
        self._wave_period_spin.setRange(0.1, 600.0)
        self._wave_period_spin.setDecimals(2)
        self._wave_period_spin.setSingleStep(0.1)
        self._wave_period_spin.setValue(3.0)
        self._wave_period_spin.valueChanged.connect(self._on_wave_param_changed)
        g.addWidget(self._wave_period_spin, 0, 4)
        g.addWidget(self._unit_label(_("Juxie.Unit.S")), 0, 5)

        self._wave_iv_label = self._grid_label("Juxie.WaveInterval")
        g.addWidget(self._wave_iv_label, 0, 6)
        self._wave_iv_spin = _IntSpin()
        self._wave_iv_spin.setRange(2, 1000)
        self._wave_iv_spin.setSingleStep(1)
        self._wave_iv_spin.setValue(10)
        self._wave_iv_spin.valueChanged.connect(self._on_wave_interval_changed)
        g.addWidget(self._wave_iv_spin, 0, 7)
        g.addWidget(self._unit_label(_("Juxie.Unit.Ms")), 0, 8)

        self._wave_hold_hi_label = self._grid_label("Juxie.WaveHoldHi")
        g.addWidget(self._wave_hold_hi_label, 1, 0)
        self._wave_hold_hi_spin = _FloatSpin()
        self._wave_hold_hi_spin.setRange(0.0, 600.0)
        self._wave_hold_hi_spin.setDecimals(2)
        self._wave_hold_hi_spin.setSingleStep(0.5)
        self._wave_hold_hi_spin.setValue(5.0)
        self._wave_hold_hi_spin.valueChanged.connect(self._on_wave_param_changed)
        g.addWidget(self._wave_hold_hi_spin, 1, 1)
        g.addWidget(self._unit_label(_("Juxie.Unit.S")), 1, 2)

        self._wave_hold_lo_label = self._grid_label("Juxie.WaveHoldLo")
        g.addWidget(self._wave_hold_lo_label, 1, 3)
        self._wave_hold_lo_spin = _FloatSpin()
        self._wave_hold_lo_spin.setRange(0.0, 600.0)
        self._wave_hold_lo_spin.setDecimals(2)
        self._wave_hold_lo_spin.setSingleStep(0.5)
        self._wave_hold_lo_spin.setValue(5.0)
        self._wave_hold_lo_spin.valueChanged.connect(self._on_wave_param_changed)
        g.addWidget(self._wave_hold_lo_spin, 1, 4)
        g.addWidget(self._unit_label(_("Juxie.Unit.S")), 1, 5)

        wrow = QHBoxLayout()
        self._wave_btn = QPushButton(_("Juxie.WaveStart"))
        self._wave_btn.clicked.connect(self._on_wave_toggle)
        wrow.addWidget(self._wave_btn)
        self._wave_rnd_btn = QPushButton(_("Juxie.WaveRandStart"))
        self._wave_rnd_btn.clicked.connect(self._on_wave_rand_toggle)
        wrow.addWidget(self._wave_rnd_btn)
        wrow.addStretch(1)
        g.addLayout(wrow, 1, 6, 1, 3)

        self._wave_log_chk = QCheckBox(_("Juxie.WaveLog"))
        self._wave_log_chk.setChecked(True)
        self._wave_log_chk.toggled.connect(self._on_wave_log_changed)
        g.addWidget(self._wave_log_chk, 2, 0, 1, 2)
        self._wave_log_path_label = QLabel("")
        style.set_text_color(self._wave_log_path_label, style.FG_DIM)
        g.addWidget(self._wave_log_path_label, 2, 2, 1, 3)
        self._wave_open_btn = QPushButton(_("Juxie.WaveOpenCsv"))
        self._wave_open_btn.clicked.connect(self._on_wave_open_csv)
        g.addWidget(self._wave_open_btn, 2, 5)
        self._wave_cur_label = QLabel("")
        style.set_text_color(self._wave_cur_label, style.LOAD_LOW, 'font-weight: 600;')
        self._wave_cur_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        g.addWidget(self._wave_cur_label, 2, 6, 1, 3)

        self._wave_info = QLabel("")
        style.set_text_color(self._wave_info, style.FG_DIM)
        g.addWidget(self._wave_info, 3, 0, 1, 9)
        outer.addLayout(g)
        return box

    def _build_feedback(self) -> QGroupBox:
        box = self._section("Juxie.Feedback")
        lay = QGridLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)

        # 两台电机并排：0=主电机，1=镜像电机
        self._fb_labels: list = [{}, {}]
        self._fb_head: list = []
        self._fb_status: list = []
        self._fb_update: list = []
        self._fb_field_labels: list = []

        fields = [
            ("position", "Juxie.Position", "Juxie.Unit.Deg"),
            ("speed", "Juxie.Speed", "Juxie.Unit.RPM"),
            ("current", "Juxie.Current", "Juxie.Unit.mA"),
            ("temperature", "Juxie.Temperature", "Juxie.Unit.Celsius"),
            ("torque", "Juxie.Torque", "Juxie.Unit.Nm"),
            ("error_code", "Juxie.ErrorCode", ""),
            ("mode_feedback", "Juxie.ModeFeedback", ""),
        ]

        for m in (0, 1):
            col = m * 6
            head = QLabel("")
            head.setWordWrap(True)
            style.set_text_color(head, style.FG_TEXT, 'font-weight: 700;')
            self._fb_head.append(head)
            lay.addWidget(head, 0, col, 1, 6)

            for r, (key, label_key, unit_key) in enumerate(fields, start=1):
                row = 1 + (r - 1) // 2
                field_col = col + ((r - 1) % 2) * 3
                name_lbl = QLabel(_(label_key))
                lay.addWidget(name_lbl, row, field_col)
                self._fb_field_labels.append((name_lbl, label_key))
                val_lbl = QLabel(_("Juxie.NoData"))
                style.set_text_color(val_lbl, style.LOAD_LOW, 'font-weight: 600;')
                lay.addWidget(val_lbl, row, field_col + 1)
                if unit_key:
                    unit_lbl = QLabel(_(unit_key))
                    lay.addWidget(unit_lbl, row, field_col + 2)
                    self._fb_field_labels.append((unit_lbl, unit_key))
                self._fb_labels[m][key] = val_lbl

            status_row = QHBoxLayout()
            status_title = QLabel(_("Juxie.Status"))
            self._fb_field_labels.append((status_title, "Juxie.Status"))
            status_row.addWidget(status_title)
            st = QLabel("")
            style.set_text_color(st, style.LOAD_LOW)
            status_row.addWidget(st)
            status_row.addStretch(1)
            self._fb_status.append(st)
            lay.addLayout(status_row, 1 + (len(fields) + 1) // 2, col, 1, 6)

            up = QLabel("")
            style.set_text_color(up, style.FG_DIM)
            status_row.addWidget(up)
            self._fb_update.append(up)

        return box

    # ── 配置加载 ──

    def _load_config(self):
        self._dev_id_spin.blockSignals(True)
        self._dev_id_spin.setValue(int(self._cfg.get("dev_id")))
        self._dev_id_spin.blockSignals(False)

        self._enable_chk.blockSignals(True)
        self._enable_chk.setChecked(bool(self._cfg.get("enable")))
        self._enable_chk.blockSignals(False)

        self._brake_chk.blockSignals(True)
        self._brake_chk.setChecked(bool(self._cfg.get("brake")))
        self._brake_chk.blockSignals(False)

        self._auto_send_chk.blockSignals(True)
        self._auto_send_chk.setChecked(bool(self._cfg.get("auto_send")))
        self._auto_send_chk.blockSignals(False)

        self._auto_req_chk.blockSignals(True)
        self._auto_req_chk.setChecked(bool(self._cfg.get("auto_request")))
        self._auto_req_chk.blockSignals(False)

        self._req_spin.blockSignals(True)
        self._req_spin.setValue(int(self._cfg.get("req_interval")))
        self._req_spin.blockSignals(False)

        self._mit_cont_chk.blockSignals(True)
        self._mit_cont_chk.setChecked(bool(self._cfg.get("mit_continuous")))
        self._mit_cont_chk.blockSignals(False)

        self._mit_interval_spin.blockSignals(True)
        self._mit_interval_spin.setValue(int(self._cfg.get("mit_interval")))
        self._mit_interval_spin.blockSignals(False)

        self._slew_spin.blockSignals(True)
        self._slew_spin.setValue(float(self._cfg.get("slew_dps")))
        self._slew_spin.blockSignals(False)

        self._auto_clear_chk.blockSignals(True)
        self._auto_clear_chk.setChecked(bool(self._cfg.get("auto_clear")))
        self._auto_clear_chk.blockSignals(False)

        self._clear_interval_spin.blockSignals(True)
        self._clear_interval_spin.setValue(int(self._cfg.get("clear_interval")))
        self._clear_interval_spin.blockSignals(False)

        self._wave_amp_spin.blockSignals(True)
        self._wave_amp_spin.setValue(float(self._cfg.get("wave_amp")))
        self._wave_amp_spin.blockSignals(False)

        self._wave_period_spin.blockSignals(True)
        self._wave_period_spin.setValue(float(self._cfg.get("wave_period")))
        self._wave_period_spin.blockSignals(False)

        hi = float(self._cfg.get("wave_hold_hi"))
        lo = float(self._cfg.get("wave_hold_lo"))
        legacy = self._ctx.get_setting("juxie_motor.wave_hold", None)
        if legacy is not None:      # 兼容旧版单一「端点保持」
            if self._ctx.get_setting("juxie_motor.wave_hold_hi", None) is None:
                hi = float(legacy)
            if self._ctx.get_setting("juxie_motor.wave_hold_lo", None) is None:
                lo = float(legacy)

        self._wave_hold_hi_spin.blockSignals(True)
        self._wave_hold_hi_spin.setValue(hi)
        self._wave_hold_hi_spin.blockSignals(False)

        self._wave_hold_lo_spin.blockSignals(True)
        self._wave_hold_lo_spin.setValue(lo)
        self._wave_hold_lo_spin.blockSignals(False)

        self._wave_iv_spin.blockSignals(True)
        self._wave_iv_spin.setValue(int(self._cfg.get("wave_interval")))
        self._wave_iv_spin.blockSignals(False)

        self._wave_log_chk.blockSignals(True)
        self._wave_log_chk.setChecked(bool(self._cfg.get("wave_log")))
        self._wave_log_chk.blockSignals(False)

        self._mirror_chk.blockSignals(True)
        self._mirror_chk.setChecked(bool(self._cfg.get("mirror")))
        self._mirror_chk.blockSignals(False)

        self._mirror_id_spin.blockSignals(True)
        self._mirror_id_spin.setValue(int(self._cfg.get("mirror_id")))
        self._mirror_id_spin.blockSignals(False)

        self._target_max_spin.blockSignals(True)
        self._target_max_spin.setValue(float(self._cfg.get("target_max")))
        self._target_max_spin.blockSignals(False)

        self._pos_max_spin.blockSignals(True)
        self._pos_max_spin.setValue(float(self._cfg.get("pos_max")))
        self._pos_max_spin.blockSignals(False)

        self._vel_max_spin.blockSignals(True)
        self._vel_max_spin.setValue(float(self._cfg.get("vel_max")))
        self._vel_max_spin.blockSignals(False)

        self._torque_max_spin.blockSignals(True)
        tmax = float(self._cfg.get("torque_max"))
        if tmax < MIN_TORQUE_MAX:      # 历史遗留的过小量程会锁死目标力矩范围
            self._ctx.status_message(_("Juxie.ScaleReset").format(
                v=tmax, d=DEFAULT_TORQUE_MAX), 6000)
            tmax = DEFAULT_TORQUE_MAX
            self._cfg.set("torque_max", tmax)
        self._torque_max_spin.setValue(tmax)
        self._torque_max_spin.blockSignals(False)

        self._update_id_label()
        self._update_ranges()

        # MIT 目标参数（含 Kp/Kd）记忆：量程先就绪，再恢复数值并按量程夹取
        self._vel_spin.blockSignals(True)
        self._vel_spin.setValue(float(self._cfg.get("target_vel")))
        self._vel_spin.blockSignals(False)

        self._kp_spin.blockSignals(True)
        self._kp_spin.setValue(float(self._cfg.get("kp")))
        self._kp_spin.blockSignals(False)

        self._kd_spin.blockSignals(True)
        self._kd_spin.setValue(float(self._cfg.get("kd")))
        self._kd_spin.blockSignals(False)

        self._torque_spin.blockSignals(True)
        self._torque_spin.setValue(float(self._cfg.get("target_torque")))
        self._torque_spin.blockSignals(False)

        self._pos_slider.blockSignals(True)
        self._pos_slider.setValue(int(self._cfg.get("target_pos")))
        self._pos_slider.blockSignals(False)

        self._tq_raw_chk.blockSignals(True)
        self._tq_raw_chk.setChecked(bool(self._cfg.get("tq_raw_enable")))
        self._tq_raw_chk.blockSignals(False)

        self._tq_raw_spin.blockSignals(True)
        self._tq_raw_spin.setValue(int(self._cfg.get("tq_raw")))
        self._tq_raw_spin.blockSignals(False)

        mode = self._cfg.get("tq_zero_mode")
        idx = self._tq_zero_combo.findData(mode)
        self._tq_zero_combo.blockSignals(True)
        self._tq_zero_combo.setCurrentIndex(max(0, idx))
        self._tq_zero_combo.blockSignals(False)

        self._update_pos_label()
        self._update_wave_info()
        self._update_wave_log_info()

    # ── 事件处理 ──

    def _on_dev_id_changed(self, val):
        self._cfg.set("dev_id", val)
        self._slew_pos = None
        self._update_id_label()
        self._clear_feedback_display()

    def _on_mirror_changed(self, checked):
        self._cfg.set("mirror", bool(checked))
        self._slew_pos = None
        self._update_id_label()
        self._update_ranges()
        self._clear_feedback_display()
        self._update_mit_timer()

    def _on_mirror_id_changed(self, val):
        self._cfg.set("mirror_id", int(val))
        self._slew_pos = None
        self._update_id_label()
        self._clear_feedback_display()

    def _on_target_max_changed(self, val):
        self._cfg.set("target_max", float(val))
        self._update_ranges()
        self._update_id_label()

    def _motor_ids(self) -> list:
        """参与控制的电机 ID：[主] 或 [主, 镜像]。"""
        ids = [self._dev_id_spin.value()]
        if self._mirror_chk.isChecked():
            ids.append(self._mirror_id_spin.value())
        return ids

    def _zero_ids(self) -> list:
        """标零固定覆盖两台电机（主 + 镜像），与镜像开关无关。"""
        return [self._dev_id_spin.value(), self._mirror_id_spin.value()]

    def _target_primary(self) -> float:
        """主电机目标角度；镜像模式下属对称机构，限制在 0~上限。"""
        deg = self._pos_slider.value() / 10.0
        if self._mirror_chk.isChecked():
            return max(0.0, min(self._target_max_spin.value(), deg))
        return deg

    def _update_id_label(self):
        dev_id = self._dev_id_spin.value()
        tx_id = P.build_mit_single_canid(dev_id)
        rx_id = P.build_feedback_canid(dev_id)
        self._id_label.setText(f"TX=0x{tx_id:03X}  RX=0x{rx_id:03X}")
        self._update_fb_headers()

    def _update_fb_headers(self):
        ids = self._motor_ids()
        max_deg = self._target_max_spin.value()
        for m in (0, 1):
            head = self._fb_head[m]
            if m < len(ids):
                tag = _("Juxie.Primary") if m == 0 else _("Juxie.MirrorTag")
                rx = P.build_feedback_canid(ids[m])
                if self._mirror_chk.isChecked():
                    # 主电机 0~上限；镜像电机方向相反，即 -上限~0
                    rng = (f"0~{max_deg:.0f}°" if m == 0
                           else f"-{max_deg:.0f}~0°")
                else:
                    rng = f"±{self._pos_max_spin.value():.0f}°"
                head.setText(f"{tag}  ID={ids[m]}  (RX=0x{rx:03X})  {rng}")
                style.set_text_color(head, style.FG_TEXT, 'font-weight: 700;')
            else:
                head.setText(_("Juxie.NoData"))
                style.set_text_color(head, style.FG_DIM, 'font-weight: 700;')

    def _on_ctl_changed(self):
        self._cfg.set("enable", self._enable_chk.isChecked())
        self._cfg.set("brake", self._brake_chk.isChecked())

    def _on_auto_send_changed(self, checked):
        self._cfg.set("auto_send", bool(checked))

    def _on_scale_changed(self):
        self._cfg.set("pos_max", self._pos_max_spin.value())
        self._cfg.set("vel_max", self._vel_max_spin.value())
        self._cfg.set("torque_max", self._torque_max_spin.value())
        self._update_ranges()
        self._update_id_label()

    def _on_target_params_changed(self):
        self._cfg.set("target_vel", self._vel_spin.value())
        self._cfg.set("kp", self._kp_spin.value())
        self._cfg.set("kd", self._kd_spin.value())
        self._cfg.set("target_torque", self._torque_spin.value())

    def _on_tq_raw_changed(self, *_args):
        self._cfg.set("tq_raw_enable", self._tq_raw_chk.isChecked())
        self._cfg.set("tq_raw", int(self._tq_raw_spin.value()))

    def _torque_signed(self) -> bool:
        return self._tq_zero_combo.currentData() == "signed"

    def _on_tq_zero_changed(self, _index: int):
        self._cfg.set("tq_zero_mode", self._tq_zero_combo.currentData())

    def _update_kp_kd_ranges(self):
        """Kp/Kd 量程固定为文档 9 字节帧的 0~500 / 0~5。"""
        self._kp_spin.setRange(0.0, P.KP_MAX)
        self._kd_spin.setRange(0.0, P.KD_MAX)

    def _update_ranges(self):
        pos_max = self._pos_max_spin.value()
        vel_max = self._vel_max_spin.value()
        torque_max = self._torque_max_spin.value()

        self._pos_slider.blockSignals(True)
        if self._mirror_chk.isChecked():
            # 镜像模式：主电机 0 ~ 角度上限，镜像电机取负（对称为 -上限 ~ 0）
            self._pos_slider.setRange(0, int(self._target_max_spin.value() * 10))
        else:
            self._pos_slider.setRange(int(-pos_max * 10), int(pos_max * 10))
        self._pos_slider.blockSignals(False)

        self._vel_spin.blockSignals(True)
        self._vel_spin.setRange(-vel_max, vel_max)
        self._vel_spin.blockSignals(False)

        self._torque_spin.blockSignals(True)
        self._torque_spin.setRange(-torque_max, torque_max)
        self._torque_spin.blockSignals(False)

        self._update_kp_kd_ranges()
        if hasattr(self, "_torque_label"):
            self._torque_label.setText(
                f"{_('Juxie.TargetTorque')}  (±{torque_max:g} Nm)")
        self._update_pos_label()

    def _on_pos_changed(self, val):
        self._cfg.set("target_pos", int(val))
        self._update_pos_label()
        # 连续发送模式下由斜坡逼近目标，不在此处阶跃下发
        if self._mit_cont_chk.isChecked():
            return
        if self._auto_send_chk.isChecked():
            self._send_mit_frame(auto=True)

    def _update_pos_label(self):
        t = self._target_primary()
        self._pos_label.setText(f"{t:+.1f}°")
        if self._mirror_chk.isChecked():
            self._mirror_target_label.setText(
                f"{_('Juxie.MirrorTag')} {-t:+.1f}°")
        else:
            self._mirror_target_label.setText("")

    # ── 发送 ──

    def _send_sync(self) -> bool:
        if not self._ctx.is_connected():
            return False
        self._ctx.send_frame(CANFrame(can_id=P.SYNC_ID, data=b"",
                                      extended=False, fd=True, brs=True))
        return True

    def _on_request_feedback(self):
        if not self._send_sync():
            self._ctx.status_message(_("Juxie.Err.NotConnected"))

    # ── 定时请求反馈 ──
    def _on_req_tick(self):
        self._send_sync()

    def _on_auto_req_changed(self, checked: bool):
        self._cfg.set("auto_request", bool(checked))
        self._update_req_timer()

    def _on_req_interval_changed(self, value: int):
        self._cfg.set("req_interval", int(value))
        self._req_timer.setInterval(int(value))

    def _update_req_timer(self):
        if self._auto_req_chk.isChecked() and self._ctx.is_connected():
            self._req_timer.start()
        else:
            self._req_timer.stop()

    # ── 连续 MIT 控制（位置斜坡限速）──
    def _on_mit_cont_changed(self, checked: bool):
        self._cfg.set("mit_continuous", bool(checked))
        if checked:
            self._stop_wave(send_zero=False)    # 与周期往复互斥
        self._update_mit_timer()

    def _on_mit_interval_changed(self, value: int):
        self._cfg.set("mit_interval", int(value))
        self._mit_timer.setInterval(int(value))

    def _on_slew_changed(self, value: float):
        self._cfg.set("slew_dps", float(value))

    def _update_mit_timer(self):
        if (self._mit_cont_chk.isChecked() and self._ctx.is_connected()
                and self._ctx.is_fd_mode()):
            if not self._mit_timer.isActive():
                self._slew_pos = None      # 重新起步：从当前位置开始逼近
            self._mit_timer.start()
        else:
            self._mit_timer.stop()

    def _on_mit_tick(self):
        if not self._ctx.is_connected() or not self._ctx.is_fd_mode():
            self._mit_timer.stop()
            return
        target = self._target_primary()
        if self._slew_pos is None:
            # 起手用主电机当前反馈位置，避免第一帧就是阶跃
            fb = self._fb[0]
            self._slew_pos = fb.position if fb is not None else target
        slew = float(self._slew_spin.value())
        if slew > 0.0:
            step = slew * (self._mit_timer.interval() / 1000.0)
            delta = target - self._slew_pos
            if abs(delta) <= step:
                self._slew_pos = target
            else:
                self._slew_pos += step if delta > 0 else -step
        else:
            self._slew_pos = target
        self._send_mit_pair(self._slew_pos)

    def _send_mit_pair(self, pos_primary: float, clear_err: bool = False,
                       release: bool = False):
        """主电机发 +pos/+τ，镜像电机发 −pos/−τ（位置与力矩都取反对称）。"""
        ids = self._motor_ids()
        self._ctx.send_frame(self._build_mit_frame(
            clear_err=clear_err, pos_deg=pos_primary, dev_id=ids[0]))
        if len(ids) > 1:
            self._ctx.send_frame(self._build_mit_frame(
                clear_err=clear_err, pos_deg=-pos_primary, dev_id=ids[1],
                mirror=True, update_label=False))

    # ── 周期往复（参考 E1_Hand_G474 host: _wave_pos）──
    def _on_wave_param_changed(self):
        self._cfg.set("wave_amp", self._wave_amp_spin.value())
        self._cfg.set("wave_period", self._wave_period_spin.value())
        self._cfg.set("wave_hold_hi", self._wave_hold_hi_spin.value())
        self._cfg.set("wave_hold_lo", self._wave_hold_lo_spin.value())
        self._update_wave_info()

    def _on_wave_interval_changed(self, value: int):
        self._cfg.set("wave_interval", int(value))
        self._wave_timer.setInterval(int(value))

    def _update_wave_info(self):
        if self._wave_on:
            return
        amp = self._wave_amp_spin.value()
        period = self._wave_period_spin.value()
        hi = self._wave_hold_hi_spin.value()
        lo = self._wave_hold_lo_spin.value()
        self._wave_info.setText(_("Juxie.WaveIdle").format(
            amp=amp, period=period, hi=hi, lo=lo,
            total=period + hi + lo))

    def _wave_pos(self, t: float) -> float:
        """往复位置：0→A（正弦）→ 保持 A → A→0（正弦）→ 保持 0，循环。

        运动周期 T_move 内完成往返；上限端保持 T_hold_hi，0°端保持 T_hold_lo，
        两端可分别设置；正弦段两端速度≈0。
        """
        a = self._wave_amp_cur
        t_move = max(1e-6, self._wave_period_spin.value())
        h_hi = self._wave_hold_hi_spin.value()
        h_lo = self._wave_hold_lo_spin.value()
        half = t_move * 0.5
        cycle = t_move + h_hi + h_lo
        tt = t % cycle
        if tt < half:                       # 0° → 上限角
            return a * 0.5 * (1.0 - math.cos(math.pi * tt / half))
        if tt < half + h_hi:                # 在上限角保持
            return a
        if tt < t_move + h_hi:              # 上限角 → 0°
            return a * 0.5 * (1.0 + math.cos(math.pi * (tt - half - h_hi) / half))
        return 0.0                          # 在 0° 保持 h_lo

    def _on_wave_toggle(self):
        if self._wave_on and not self._wave_rand:
            self._stop_wave()
        else:
            self._start_wave(randomize=False)

    def _on_wave_rand_toggle(self):
        if self._wave_on and self._wave_rand:
            self._stop_wave()
        else:
            self._start_wave(randomize=True)

    def _wave_max_deg(self) -> float:
        """当前行程上限：镜像模式为「角度上限」，单机模式为 Pos_Max。"""
        return (self._target_max_spin.value() if self._mirror_chk.isChecked()
                else self._pos_max_spin.value())

    def _wave_cycle_len(self) -> float:
        return (max(1e-6, self._wave_period_spin.value())
                + self._wave_hold_hi_spin.value()
                + self._wave_hold_lo_spin.value())

    def _wave_update_cycle(self, t: float):
        """每 tick 更新本周期幅值：固定模式跟随上限角，随机模式每周期重取。"""
        if not self._wave_rand:
            self._wave_amp_cur = self._wave_amp_spin.value()
            return
        idx = int(t / self._wave_cycle_len())
        if idx != self._wave_cur_idx:
            self._wave_cur_idx = idx
            mx = max(1e-6, self._wave_max_deg())
            self._wave_amp_cur = random.uniform(WAVE_RAND_MIN_FRAC * mx, mx)
            self._update_wave_info_live()

    def _update_wave_buttons(self):
        self._wave_btn.setText(
            _("Juxie.WaveStop")
            if (self._wave_on and not self._wave_rand) else _("Juxie.WaveStart"))
        self._wave_rnd_btn.setText(
            _("Juxie.WaveRandStop")
            if (self._wave_on and self._wave_rand) else _("Juxie.WaveRandStart"))

    def _update_wave_info_live(self):
        """运行中的状态行（含本周期实际幅值）。"""
        if not self._wave_on:
            self._update_wave_info()
            return
        hi = self._wave_hold_hi_spin.value()
        lo = self._wave_hold_lo_spin.value()
        period = self._wave_period_spin.value()
        key = ("Juxie.WaveRandRunning" if self._wave_rand
               else "Juxie.WaveRunning")
        self._wave_info.setText(_(key).format(
            amp=self._wave_amp_cur, period=period, hi=hi, lo=lo,
            total=period + hi + lo))
        self._wave_cur_label.setText(
            _("Juxie.WaveCurAmp").format(amp=self._wave_amp_cur)
            if self._wave_rand else "")

    def _start_wave(self, randomize: bool = False):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        if not self._ctx.is_fd_mode():
            self._ctx.status_message(_("Juxie.Err.NeedFd"))
            return
        if self._wave_on:
            self._stop_wave(send_zero=False)
        amp = self._wave_amp_spin.value()
        max_deg = self._wave_max_deg()
        if amp > max_deg:                   # 上限角不超过当前行程
            amp = max_deg
            self._wave_amp_spin.setValue(amp)   # 触发保存与信息刷新
        # 与连续 MIT 互斥
        self._mit_cont_chk.setChecked(False)
        self._slew_pos = None
        self._wave_rand = bool(randomize)
        self._wave_cur_idx = -1
        self._wave_amp_cur = amp
        self._wave_on = True
        self._wave_t0 = time.monotonic()
        self._open_wave_log()
        self._wave_timer.setInterval(int(self._wave_iv_spin.value()))
        self._wave_timer.start()
        self._update_wave_buttons()
        self._update_wave_info_live()

    def _stop_wave(self, send_zero: bool = True):
        was_on = self._wave_on
        self._wave_on = False
        self._wave_rand = False
        self._wave_cur_idx = -1
        self._wave_timer.stop()
        self._wave_cur_label.setText("")
        self._update_wave_buttons()
        self._update_wave_info()
        if send_zero and was_on and self._ctx.is_connected() and self._ctx.is_fd_mode():
            self._slew_pos = 0.0
            self._send_mit_pair(0.0)        # 停止时目标回 0°

    def _on_wave_tick(self):
        if not self._ctx.is_connected() or not self._ctx.is_fd_mode():
            self._stop_wave(send_zero=False)
            return
        t = time.monotonic() - self._wave_t0
        self._wave_update_cycle(t)
        pos = self._wave_pos(t)
        self._slew_pos = pos
        self._send_mit_pair(pos)
        self._maybe_log_hold_mid(t)

    # ── 上限保持中点记录（每个周期一行）──
    def _on_wave_log_changed(self, checked: bool):
        self._cfg.set("wave_log", bool(checked))
        self._update_wave_log_info()

    def _update_wave_log_info(self):
        if self._wave_log_file:
            self._wave_log_path_label.setText(
                f"{_('Juxie.WaveLogFile')}: "
                f"{os.path.basename(self._wave_log_file)}  "
                f"({self._wave_log_rows})")
        else:
            self._wave_log_path_label.setText(_("Juxie.WaveLogNone"))

    def _on_wave_open_csv(self):
        path = self._wave_log_file
        if not path or not os.path.exists(path):
            self._ctx.status_message(_("Juxie.WaveLogNone"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_wave_log(self):
        """开始往复时新建 CSV；未勾选记录则关闭记录。"""
        self._wave_log_rows = 0
        self._wave_last_cycle = -1
        self._wave_log_file = None
        if not self._wave_log_chk.isChecked():
            self._update_wave_log_info()
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_base_dir(), f"juxie_wave_{stamp}.csv")
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(WAVE_LOG_HEADER)
        except OSError as exc:
            logger.warning("创建往复记录文件失败: %s", exc)
            self._ctx.status_message(_("Juxie.WaveLogFail"))
            self._update_wave_log_info()
            return
        self._wave_log_file = path
        self._update_wave_log_info()
        self._ctx.status_message(
            f"{_('Juxie.WaveLogFile')}: {os.path.basename(path)}", 4000)

    def _maybe_log_hold_mid(self, t: float):
        """到达「上限保持」时间中点时记录一次（每周期仅一次）。"""
        if not self._wave_log_file:
            return
        t_move = max(1e-6, self._wave_period_spin.value())
        hi = self._wave_hold_hi_spin.value()
        lo = self._wave_hold_lo_spin.value()
        cycle = t_move + hi + lo
        idx = int(t // cycle)
        if t % cycle >= t_move * 0.5 + hi * 0.5 and idx != self._wave_last_cycle:
            self._wave_last_cycle = idx
            self._write_wave_row(idx + 1, t)

    def _write_wave_row(self, cycle_no: int, t: float):
        cmd = self._wave_amp_cur          # 本周期实际幅值（随机模式即随机上限角）
        kp = self._kp_spin.value()
        kd = self._kd_spin.value()
        fb0, fb1 = self._fb[0], self._fb[1]
        p = fb0.position if fb0 is not None else None
        m = fb1.position if fb1 is not None else None
        row = [
            cycle_no, f"{t:.3f}", f"{cmd:.3f}", f"{kp:.3f}", f"{kd:.3f}",
            "" if p is None else f"{p:.3f}",
            "" if m is None else f"{m:.3f}",
            "" if p is None else f"{p - cmd:.3f}",
            "" if m is None else f"{m + cmd:.3f}",
        ]
        try:
            with open(self._wave_log_file, "a", newline="",
                      encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(row)
        except OSError as exc:
            logger.warning("写入往复记录失败: %s", exc)
            return
        self._wave_log_rows += 1
        self._update_wave_log_info()

    def _build_mit_frame(self, clear_err: bool = False,
                         pos_deg: float | None = None,
                         dev_id: int | None = None,
                         mirror: bool = False,
                         update_label: bool = True) -> CANFrame | None:
        if dev_id is None:
            dev_id = self._dev_id_spin.value()
        if pos_deg is None:
            pos_deg = self._target_primary()
        # 镜像电机：前馈扭矩取负（与位置取负一致）
        torque_nm = (-self._torque_spin.value() if mirror
                     else self._torque_spin.value())
        tq_raw = None
        if self._tq_raw_chk.isChecked():
            raw = int(self._tq_raw_spin.value())
            if mirror:
                # 居中映射关于 2048 对称 -> 4095-raw；有符号则取 12bit 补码
                raw = ((-raw) & 0x0FFF) if self._torque_signed() else (4095 - raw)
            tq_raw = raw
        payload = P.build_mit_control(
            dev_id,
            self._enable_chk.isChecked(),
            self._brake_chk.isChecked(),
            clear_err,
            pos_deg,
            self._vel_spin.value(),
            self._kp_spin.value(),
            self._kd_spin.value(),
            torque_nm,
            self._pos_max_spin.value(),
            self._vel_max_spin.value(),
            self._torque_max_spin.value(),
            torque_raw=tq_raw,
            torque_signed=self._torque_signed(),
        )
        if update_label:
            self._update_frame_label(payload)
        return CANFrame(can_id=P.build_mit_single_canid(dev_id),
                        data=bytes(payload),
                        extended=False, fd=True, brs=True)

    def _update_frame_label(self, payload: bytes):
        """显示最后一帧 MIT 的原始字段，便于核对协议映射是否合理。"""
        if not hasattr(self, "_frame_label"):
            return
        ctrl = payload[0]
        pos_raw = (payload[1] << 8) | payload[2]
        vel_raw = (payload[3] << 4) | (payload[4] >> 4)
        kp_raw = ((payload[4] & 0x0F) << 8) | payload[5]
        kd_raw = (payload[6] << 4) | (payload[7] >> 4)
        tq_raw = ((payload[7] & 0x0F) << 8) | payload[8]
        tq_max = max(1e-9, self._torque_max_spin.value())
        tq_nm = P.raw_to_torque(tq_raw, tq_max, self._torque_signed())
        self._frame_label.setText(
            f"frame: ctrl=0x{ctrl:02X} pos={pos_raw} vel={vel_raw} "
            f"kp={kp_raw} kd={kd_raw} tq={tq_raw} (~{tq_nm:+.3f} Nm)")

    def _send_mit_frame(self, auto: bool = False, clear_err: bool = False):
        if not self._ctx.is_connected():
            if not auto:
                self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        # MIT 帧为 9 字节，必须使用 CAN FD
        if not self._ctx.is_fd_mode():
            if not auto:
                self._ctx.status_message(_("Juxie.Err.NeedFd"))
            return
        self._send_mit_pair(self._target_primary(), clear_err)

    def _on_send_mit(self):
        self._send_mit_frame()

    # ── 清除故障：短促脉冲 ──
    def _on_clear_error(self):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        if not self._ctx.is_fd_mode():
            self._ctx.status_message(_("Juxie.Err.NeedFd"))
            return
        self._clear_watch_timer.stop()
        self._clear_burst_left = CLEAR_BURST_FRAMES
        self._send_clear_tick()
        self._clear_burst_timer.start()

    def _send_clear_tick(self):
        if not self._ctx.is_connected() or not self._ctx.is_fd_mode():
            self._clear_burst_timer.stop()
            self._clear_burst_left = 0
            return
        if self._clear_burst_left <= 0:
            # 脉冲结束：发一帧释放帧（清错位归 0），再观察反馈错误码
            self._clear_burst_timer.stop()
            self._clear_pending = True
            self._ctx.status_message(_("Juxie.ClearSent"), 3000)
            self._clear_release_timer.start()
            self._clear_watch_timer.start(CLEAR_WATCH_MS)
            return
        self._clear_burst_left -= 1
        self._send_mit_pair(self._clear_position(), clear_err=True)

    def _on_clear_watch_timeout(self):
        if not self._clear_pending:
            return
        self._clear_pending = False
        fb = self._fb[0]
        if fb is None:
            self._ctx.status_message(_("Juxie.ClearNoFeedback"), 4000)
        else:
            self._ctx.status_message(
                _("Juxie.ClearFailed").format(code=f"0x{fb.error_code:04X}"), 5000)

    def _hold_position(self) -> float | None:
        """清错脉冲用的位置目标：保持当前指令/反馈位置，避免顺带的位置阶跃。"""
        if self._slew_pos is not None:
            return self._slew_pos
        if self._fb[0] is not None:
            return self._fb[0].position
        return None

    def _clear_position(self) -> float:
        """清错帧的位置：优先保持位置，其次沿用当前目标（避免误发 0°）。"""
        pos = self._hold_position()
        return pos if pos is not None else self._target_primary()

    def _on_clear_release(self):
        """清错脉冲后发一帧不带清错位的帧，保证下次清错仍有 0→1 跳变。"""
        if not self._ctx.is_connected() or not self._ctx.is_fd_mode():
            return
        self._send_mit_pair(self._clear_position())

    # ── 周期清错 ──
    def _on_auto_clear_changed(self, checked: bool):
        self._cfg.set("auto_clear", bool(checked))
        self._update_clear_timer()

    def _on_clear_interval_changed(self, value: int):
        self._cfg.set("clear_interval", int(value))
        self._auto_clear_timer.setInterval(int(value))

    def _update_clear_timer(self):
        if (self._auto_clear_chk.isChecked() and self._ctx.is_connected()
                and self._ctx.is_fd_mode()):
            if not self._auto_clear_timer.isActive():
                self._on_auto_clear_tick()      # 立即清一次，不必等满一个周期
            self._auto_clear_timer.start()
        else:
            self._auto_clear_timer.stop()
            self._clear_release_timer.stop()    # 取消挂起的释放帧，避免停止后仍发帧

    def _on_auto_clear_tick(self):
        if not self._ctx.is_connected() or not self._ctx.is_fd_mode():
            self._auto_clear_timer.stop()
            return
        self._send_mit_pair(self._clear_position(), clear_err=True)
        # 释放延时取周期的 1/2（不超过 15ms），保证清错位在下一拍之前归 0，
        # 这样即使周期很短（如 10ms）每拍依然有 0→1 跳变
        period = max(1, int(self._auto_clear_timer.interval()))
        release = max(1, min(CLEAR_BURST_MS, period // 2))
        if not self._clear_release_timer.isActive():
            # 已在计时的释放帧不重排，避免系统繁忙时被无限推迟（清错位一直为高）
            self._clear_release_timer.start(release)

    def _stop_clear(self):
        self._clear_burst_timer.stop()
        self._clear_watch_timer.stop()
        self._auto_clear_timer.stop()
        self._clear_release_timer.stop()
        self._clear_burst_left = 0
        self._clear_pending = False

    # ── 标零（CANopen SDO 0x2531=1）──
    def _on_zero(self):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        if not self._ctx.is_fd_mode():
            self._ctx.status_message(_("Juxie.Err.NeedFd"))
            return
        ret = QMessageBox.warning(
            self, _("Juxie.Zero"), _("Juxie.ZeroConfirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if ret != QMessageBox.StandardButton.Yes:
            return
        # 标零两台电机（与镜像开关无关：主 + 镜像都要标零）
        ids = list(dict.fromkeys(self._zero_ids()))     # 去重，避免两路同 ID 时重复发
        for dev_id in ids:
            self._ctx.send_frame(CANFrame(
                can_id=P.build_zero_canid(dev_id),
                data=P.SDO_ZERO_DATA, extended=False, fd=True, brs=True))
        self._ctx.status_message(_("Juxie.ZeroSent"), 3000)

    # ── 反馈处理 ──

    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        ids = self._motor_ids()
        route = {P.build_feedback_canid(d): m for m, d in enumerate(ids)}
        sdo_resp_ids = {P.SDO_RESP_ID_BASE | d for d in ids}
        sdo_resp_ids.add(P.SDO_RESP_ID_BASE | self._dev_id_spin.value())

        for f in frames:
            if f.is_tx or f.is_error:
                continue
            if f.can_id in sdo_resp_ids:
                self._on_sdo_response(f.data)
                continue
            m = route.get(f.can_id)
            if m is None:
                continue
            fb = P.parse_feedback(f.data)
            if fb is None:
                continue
            self._fb[m] = fb
            self._last_rx[m] = time.monotonic()
            self._update_feedback_display(m)
            if (self._sdo_expect_mode
                    and fb.mode_feedback == SDO_MODE_FEEDBACK.get(
                        self._sdo_expect_mode)):
                self._sdo_success()
            if self._clear_pending and fb.error_code == 0:
                self._clear_pending = False
                self._clear_watch_timer.stop()
                self._ctx.status_message(_("Juxie.ClearOk"), 4000)

    def _update_feedback_display(self, m: int = 0):
        fb = self._fb[m]
        if fb is None:
            return
        labels = self._fb_labels[m]

        labels["position"].setText(f"{fb.position:+.2f}")
        labels["speed"].setText(str(fb.speed))
        labels["current"].setText(str(fb.current))
        labels["temperature"].setText(f"{fb.temperature:.1f}")
        labels["torque"].setText(
            f"{fb.torque:.2f}" if fb.torque is not None else _("Juxie.NoData"))
        labels["error_code"].setText(f"0x{fb.error_code:04X}")
        labels["mode_feedback"].setText(self._mode_name(fb.mode_feedback))

        if fb.error_code != 0:
            style.set_text_color(labels["error_code"], style.LOAD_HIGH, 'font-weight: 600;')
        else:
            style.set_text_color(labels["error_code"], style.LOAD_LOW, 'font-weight: 600;')

        status_parts = []
        status_parts.append(_("Juxie.Status.Enabled") if fb.enabled else _("Juxie.Status.Disabled"))
        status_parts.append(_("Juxie.Status.BrakeOff") if fb.brake_released else _("Juxie.Status.BrakeOn"))
        status_parts.append(_("Juxie.Status.Error") if fb.has_error else _("Juxie.Status.Normal"))
        status_parts.append(_("Juxie.Status.InPosition") if fb.position_reached else _("Juxie.Status.Running"))
        self._fb_status[m].setText("  |  ".join(status_parts))

        age = time.monotonic() - self._last_rx[m]
        if age < 2.0:
            self._fb_update[m].setText(f"{_('Juxie.LastUpdate')}: {age:.1f}s")
            style.set_text_color(self._fb_update[m], style.LOAD_LOW)
        else:
            self._fb_update[m].setText(_("Juxie.Offline"))
            style.set_text_color(self._fb_update[m], style.LOAD_MID)

    def _mode_name(self, mode_val: int) -> str:
        name_map = {
            0x01: "Juxie.Mode.ProfilePos",
            0x02: "Juxie.Mode.ProfileVel",
            0x03: "Juxie.Mode.CSP",
            0x04: "Juxie.Mode.CSV",
            0x05: "Juxie.Mode.Current",
            0x06: "Juxie.Mode.Torque",
            0x0A: "Juxie.Mode.MIT",
        }
        key = name_map.get(mode_val)
        return _(key) if key else f"0x{mode_val:02X}"

    # ── 生命周期 ──

    def on_activated(self):
        self._update_req_timer()
        self._update_mit_timer()
        self._update_clear_timer()

    def on_deactivating(self):
        self._req_timer.stop()
        self._mit_timer.stop()
        self._wave_timer.stop()
        self._wave_on = False
        self._sdo_timer.stop()
        self._sdo_read_timer.stop()
        self._sdo_expect_mode = 0
        self._sdo_retry_args = None
        self._sdo_queue = []
        self._stop_clear()

    def on_connect(self):
        self._fb = [None, None]
        self._last_rx = [0.0, 0.0]
        self._slew_pos = None
        self._clear_feedback_display()
        self._update_req_timer()
        self._update_mit_timer()
        self._update_clear_timer()

    def on_disconnect(self):
        self._req_timer.stop()
        self._mit_timer.stop()
        self._sdo_timer.stop()
        self._sdo_read_timer.stop()
        self._sdo_expect_mode = 0
        self._sdo_retry_args = None
        self._sdo_queue = []
        self._stop_wave(send_zero=False)
        self._stop_clear()
        self._fb = [None, None]
        self._last_rx = [0.0, 0.0]
        self._slew_pos = None
        self._clear_feedback_display()
        for up in self._fb_update:
            up.setText(_("Juxie.Offline"))
            style.set_text_color(up, style.LOAD_MID)

    def _clear_feedback_display(self):
        for m in (0, 1):
            for key in self._fb_labels[m]:
                lbl = self._fb_labels[m][key]
                lbl.setText(_("Juxie.NoData"))
                style.set_text_color(lbl, style.LOAD_LOW, 'font-weight: 600;')
            self._fb_status[m].setText("")
            self._fb_update[m].setText("")

    def refresh_language(self):
        for section, key in self._sections:
            section.setTitle(_(key))
        self._update_id_label()
        self._update_pos_label()
        self._update_ranges()
        self._sync_btn.setText(_("Juxie.RequestFeedback"))
        self._send_btn.setText(_("Juxie.SendMIT"))
        self._frame_label.setToolTip(_("Juxie.FrameTip"))
        self._tq_raw_chk.setText(_("Juxie.TorqueRaw"))
        self._tq_raw_chk.setToolTip(_("Juxie.TorqueRawTip"))
        self._tq_raw_spin.setToolTip(_("Juxie.TorqueRawTip"))
        self._tq_zero_combo.setToolTip(_("Juxie.TorqueZeroTip"))
        cur = self._tq_zero_combo.currentData()
        self._tq_zero_combo.blockSignals(True)
        self._tq_zero_combo.setItemText(0, _("Juxie.TorqueZeroOffset"))
        self._tq_zero_combo.setItemText(1, _("Juxie.TorqueZeroSigned"))
        self._tq_zero_combo.setCurrentIndex(max(0, self._tq_zero_combo.findData(cur)))
        self._tq_zero_combo.blockSignals(False)
        self._dev_id_label.setText(_("Juxie.DevID"))
        self._mirror_chk.setText(_("Juxie.Mirror"))
        self._mirror_id_label.setText(_("Juxie.MirrorID"))
        self._target_max_label.setText(_("Juxie.TargetMax"))
        self._enable_chk.setText(_("Juxie.Enable"))
        self._brake_chk.setText(_("Juxie.Brake"))
        self._clear_err_btn.setText(_("Juxie.ClearError"))
        self._zero_btn.setText(_("Juxie.Zero"))
        self._auto_send_chk.setText(_("Juxie.AutoSend"))
        self._auto_req_chk.setText(_("Juxie.AutoRequest"))
        self._req_label.setText(_("Juxie.ReqInterval"))
        self._mit_cont_chk.setText(_("Juxie.Continuous"))
        self._mit_int_label.setText(_("Juxie.MitInterval"))
        self._slew_label.setText(_("Juxie.SlewRate"))
        self._auto_clear_chk.setText(_("Juxie.AutoClear"))
        self._auto_clear_label.setText(_("Juxie.ClearInterval"))
        self._wave_amp_label.setText(_("Juxie.WaveAmp"))
        self._wave_period_label.setText(_("Juxie.WavePeriod"))
        self._wave_hold_hi_label.setText(_("Juxie.WaveHoldHi"))
        self._wave_hold_lo_label.setText(_("Juxie.WaveHoldLo"))
        self._wave_iv_label.setText(_("Juxie.WaveInterval"))
        self._update_wave_buttons()
        self._update_wave_info_live()
        self._wave_log_chk.setText(_("Juxie.WaveLog"))
        self._wave_open_btn.setText(_("Juxie.WaveOpenCsv"))
        self._sdo_cur_label.setText(_("Juxie.SdoCurrent"))
        self._sdo_tq_label.setText(_("Juxie.SdoTorque"))
        self._sdo_cur_btn.setText(_("Juxie.SdoApplyCurrent"))
        self._sdo_tq_btn.setText(_("Juxie.SdoApplyTorque"))
        self._sdo_zero_btn.setText(_("Juxie.SdoZero"))
        self._sdo_hint.setText(_("Juxie.SdoHint"))
        self._update_wave_log_info()
        for lbl, key in self._fb_field_labels:
            lbl.setText(_(key))
        self._update_fb_headers()
        for m in (0, 1):
            self._update_feedback_display(m)
