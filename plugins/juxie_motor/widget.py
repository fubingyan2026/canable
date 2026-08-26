"""捷电机 MIT 控制 UI 面板。"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QGridLayout,
                                QGroupBox, QHBoxLayout, QLabel, QPushButton,
                                QSlider, QSpinBox, QVBoxLayout, QWidget)

from cangui.i18n import _
from cangui import style
from canable_sdk.frame import CANFrame

from . import protocol as P

logger = logging.getLogger("plugin.juxie_motor")

_OK = style.LOAD_LOW
_WARN = style.LOAD_MID
_ERR = style.LOAD_HIGH
_DIM = style.FG_DIM
_TEXT = style.FG_TEXT


class _ConfigStore:
    PLUGIN_NAME = "juxie_motor"
    DEFAULTS = {
        "dev_id": 0,
        "enable": True,
        "brake": True,
        "clear_err": False,
        "auto_send": True,
        "pos_max": 180.0,
        "vel_max": 500.0,
        "torque_max": 20.0,
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
        self._feedback = None
        self._last_rx = 0.0

        self._build_ui()
        self._load_config()

    # ── UI 构建 ──

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_dev_config())
        root.addWidget(self._build_mit_control())
        root.addWidget(self._build_feedback())
        root.addStretch(1)

    def _build_dev_config(self) -> QGroupBox:
        box = QGroupBox(_("Juxie.DevConfig"))
        lay = QHBoxLayout(box)

        lay.addWidget(QLabel(_("Juxie.DevID")))
        self._dev_id_spin = QSpinBox()
        self._dev_id_spin.setRange(0, 127)
        self._dev_id_spin.setValue(0)
        self._dev_id_spin.valueChanged.connect(self._on_dev_id_changed)
        lay.addWidget(self._dev_id_spin)

        self._id_label = QLabel()
        self._id_label.setStyleSheet(f"color: {_DIM};")
        lay.addWidget(self._id_label)
        lay.addStretch(1)

        self._sync_btn = QPushButton(_("Juxie.RequestFeedback"))
        self._sync_btn.clicked.connect(self._on_request_feedback)
        lay.addWidget(self._sync_btn)
        return box

    def _build_mit_control(self) -> QGroupBox:
        box = QGroupBox(_("Juxie.MITControl"))
        lay = QVBoxLayout(box)

        ctl_row = QHBoxLayout()
        self._enable_chk = QCheckBox(_("Juxie.Enable"))
        self._enable_chk.toggled.connect(self._on_ctl_changed)
        ctl_row.addWidget(self._enable_chk)
        self._brake_chk = QCheckBox(_("Juxie.Brake"))
        self._brake_chk.toggled.connect(self._on_ctl_changed)
        ctl_row.addWidget(self._brake_chk)
        self._clear_err_chk = QCheckBox(_("Juxie.ClearError"))
        self._clear_err_chk.toggled.connect(self._on_ctl_changed)
        ctl_row.addWidget(self._clear_err_chk)
        self._auto_send_chk = QCheckBox(_("Juxie.AutoSend"))
        self._auto_send_chk.setChecked(True)
        self._auto_send_chk.toggled.connect(self._on_auto_send_changed)
        ctl_row.addWidget(self._auto_send_chk)
        ctl_row.addStretch(1)
        lay.addLayout(ctl_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel(_("Juxie.PosMax")))
        self._pos_max_spin = QDoubleSpinBox()
        self._pos_max_spin.setRange(1.0, 360.0)
        self._pos_max_spin.setDecimals(1)
        self._pos_max_spin.setValue(180.0)
        self._pos_max_spin.setSuffix(" °")
        self._pos_max_spin.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self._pos_max_spin)

        scale_row.addWidget(QLabel(_("Juxie.VelMax")))
        self._vel_max_spin = QDoubleSpinBox()
        self._vel_max_spin.setRange(1.0, 100000.0)
        self._vel_max_spin.setDecimals(0)
        self._vel_max_spin.setValue(500.0)
        self._vel_max_spin.setSuffix(" RPM")
        self._vel_max_spin.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self._vel_max_spin)

        scale_row.addWidget(QLabel(_("Juxie.TorqueMax")))
        self._torque_max_spin = QDoubleSpinBox()
        self._torque_max_spin.setRange(0.1, 1000.0)
        self._torque_max_spin.setDecimals(1)
        self._torque_max_spin.setValue(20.0)
        self._torque_max_spin.setSuffix(" Nm")
        self._torque_max_spin.valueChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self._torque_max_spin)
        scale_row.addStretch(1)
        lay.addLayout(scale_row)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel(_("Juxie.TargetPos")))
        self._pos_slider = QSlider(Qt.Horizontal)
        self._pos_slider.setRange(-1800, 1800)
        self._pos_slider.setSingleStep(5)
        self._pos_slider.setPageStep(50)
        self._pos_slider.setValue(0)
        self._pos_slider.valueChanged.connect(self._on_pos_changed)
        pos_row.addWidget(self._pos_slider, 1)
        self._pos_label = QLabel("+0.0°")
        self._pos_label.setFixedWidth(56)
        self._pos_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._pos_label.setStyleSheet(f"color: {_DIM};")
        pos_row.addWidget(self._pos_label)
        lay.addLayout(pos_row)

        grid = QGridLayout()
        grid.addWidget(QLabel(_("Juxie.TargetVel")), 0, 0)
        self._vel_spin = QDoubleSpinBox()
        self._vel_spin.setRange(-500.0, 500.0)
        self._vel_spin.setDecimals(1)
        self._vel_spin.setValue(0.0)
        self._vel_spin.setSuffix(" RPM")
        grid.addWidget(self._vel_spin, 0, 1)

        grid.addWidget(QLabel(_("Juxie.Kp")), 0, 2)
        self._kp_spin = QDoubleSpinBox()
        self._kp_spin.setRange(0.0, 500.0)
        self._kp_spin.setDecimals(1)
        self._kp_spin.setValue(0.0)
        grid.addWidget(self._kp_spin, 0, 3)

        grid.addWidget(QLabel(_("Juxie.Kd")), 1, 0)
        self._kd_spin = QDoubleSpinBox()
        self._kd_spin.setRange(0.0, 5.0)
        self._kd_spin.setDecimals(2)
        self._kd_spin.setValue(0.0)
        grid.addWidget(self._kd_spin, 1, 1)

        grid.addWidget(QLabel(_("Juxie.TargetTorque")), 1, 2)
        self._torque_spin = QDoubleSpinBox()
        self._torque_spin.setRange(-20.0, 20.0)
        self._torque_spin.setDecimals(2)
        self._torque_spin.setValue(0.0)
        self._torque_spin.setSuffix(" Nm")
        grid.addWidget(self._torque_spin, 1, 3)
        lay.addLayout(grid)

        self._send_btn = QPushButton(_("Juxie.SendMIT"))
        self._send_btn.clicked.connect(self._on_send_mit)
        lay.addWidget(self._send_btn)
        return box

    def _build_feedback(self) -> QGroupBox:
        box = QGroupBox(_("Juxie.Feedback"))
        lay = QGridLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)

        self._fb_labels: dict[str, QLabel] = {}
        fields = [
            ("position", _("Juxie.Position"), _("Juxie.Unit.Deg")),
            ("speed", _("Juxie.Speed"), _("Juxie.Unit.RPM")),
            ("current", _("Juxie.Current"), _("Juxie.Unit.mA")),
            ("temperature", _("Juxie.Temperature"), _("Juxie.Unit.Celsius")),
            ("torque", _("Juxie.Torque"), _("Juxie.Unit.Nm")),
            ("error_code", _("Juxie.ErrorCode"), ""),
            ("mode_feedback", _("Juxie.ModeFeedback"), ""),
        ]

        for row_idx, (key, label_key, unit_key) in enumerate(fields):
            r, c = row_idx // 2, (row_idx % 2) * 3
            lay.addWidget(QLabel(_(label_key)), r, c)
            val_lbl = QLabel(_("Juxie.NoData"))
            val_lbl.setStyleSheet(f"color: {_TEXT}; font-weight: 600;")
            lay.addWidget(val_lbl, r, c + 1)
            if unit_key:
                lay.addWidget(QLabel(_(unit_key)), r, c + 2)
            self._fb_labels[key] = val_lbl

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel(_("Juxie.Status")))
        self._fb_status = QLabel("")
        self._fb_status.setStyleSheet(f"color: {_DIM};")
        status_row.addWidget(self._fb_status)
        status_row.addStretch(1)
        lay.addLayout(status_row, (len(fields) + 1) // 2, 0, 1, 6)

        update_row = QHBoxLayout()
        self._fb_update = QLabel("")
        self._fb_update.setStyleSheet(f"color: {_DIM};")
        update_row.addWidget(self._fb_update)
        update_row.addStretch(1)
        lay.addLayout(update_row, (len(fields) + 1) // 2 + 1, 0, 1, 6)

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

        self._clear_err_chk.blockSignals(True)
        self._clear_err_chk.setChecked(bool(self._cfg.get("clear_err")))
        self._clear_err_chk.blockSignals(False)

        self._auto_send_chk.blockSignals(True)
        self._auto_send_chk.setChecked(bool(self._cfg.get("auto_send")))
        self._auto_send_chk.blockSignals(False)

        self._pos_max_spin.blockSignals(True)
        self._pos_max_spin.setValue(float(self._cfg.get("pos_max")))
        self._pos_max_spin.blockSignals(False)

        self._vel_max_spin.blockSignals(True)
        self._vel_max_spin.setValue(float(self._cfg.get("vel_max")))
        self._vel_max_spin.blockSignals(False)

        self._torque_max_spin.blockSignals(True)
        self._torque_max_spin.setValue(float(self._cfg.get("torque_max")))
        self._torque_max_spin.blockSignals(False)

        self._update_id_label()
        self._update_ranges()

    # ── 事件处理 ──

    def _on_dev_id_changed(self, val):
        self._cfg.set("dev_id", val)
        self._update_id_label()

    def _update_id_label(self):
        dev_id = self._dev_id_spin.value()
        tx_id = P.build_mit_single_canid(dev_id)
        rx_id = P.build_feedback_canid(dev_id)
        self._id_label.setText(f"TX=0x{tx_id:03X}  RX=0x{rx_id:03X}")

    def _on_ctl_changed(self):
        self._cfg.set("enable", self._enable_chk.isChecked())
        self._cfg.set("brake", self._brake_chk.isChecked())
        self._cfg.set("clear_err", self._clear_err_chk.isChecked())

    def _on_auto_send_changed(self, checked):
        self._cfg.set("auto_send", bool(checked))

    def _on_scale_changed(self):
        self._cfg.set("pos_max", self._pos_max_spin.value())
        self._cfg.set("vel_max", self._vel_max_spin.value())
        self._cfg.set("torque_max", self._torque_max_spin.value())
        self._update_ranges()

    def _update_ranges(self):
        pos_max = self._pos_max_spin.value()
        vel_max = self._vel_max_spin.value()
        torque_max = self._torque_max_spin.value()

        self._pos_slider.blockSignals(True)
        self._pos_slider.setRange(int(-pos_max * 10), int(pos_max * 10))
        self._pos_slider.blockSignals(False)

        self._vel_spin.blockSignals(True)
        self._vel_spin.setRange(-vel_max, vel_max)
        self._vel_spin.blockSignals(False)

        self._torque_spin.blockSignals(True)
        self._torque_spin.setRange(-torque_max, torque_max)
        self._torque_spin.blockSignals(False)

        self._update_pos_label()

    def _on_pos_changed(self, val):
        self._update_pos_label()
        if self._auto_send_chk.isChecked():
            self._send_mit_frame(auto=True)

    def _update_pos_label(self):
        deg = self._pos_slider.value() / 10.0
        self._pos_label.setText(f"{deg:+.1f}°")

    # ── 发送 ──

    def _on_request_feedback(self):
        if not self._ctx.is_connected():
            self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        frame = CANFrame(can_id=P.SYNC_ID, data=b"", extended=False, fd=True, brs=True)
        self._ctx.send_frame(frame)

    def _build_mit_frame(self) -> CANFrame | None:
        dev_id = self._dev_id_spin.value()
        payload = P.build_mit_control(
            dev_id,
            self._enable_chk.isChecked(),
            self._brake_chk.isChecked(),
            self._clear_err_chk.isChecked(),
            self._pos_slider.value() / 10.0,
            self._vel_spin.value(),
            self._kp_spin.value(),
            self._kd_spin.value(),
            self._torque_spin.value(),
            self._pos_max_spin.value(),
            self._vel_max_spin.value(),
            self._torque_max_spin.value(),
        )
        return CANFrame(can_id=P.build_mit_single_canid(dev_id), data=payload,
                        extended=False, fd=True, brs=True)

    def _send_mit_frame(self, auto: bool = False):
        if not self._ctx.is_connected():
            if not auto:
                self._ctx.status_message(_("Juxie.Err.NotConnected"))
            return
        frame = self._build_mit_frame()
        self._ctx.send_frame(frame)

    def _on_send_mit(self):
        self._send_mit_frame()

    # ── 反馈处理 ──

    def on_frames(self, frames):
        if not self._ctx.is_connected():
            return
        dev_id = self._dev_id_spin.value()
        target_id = P.build_feedback_canid(dev_id)

        for f in frames:
            if f.is_tx or f.is_error or f.can_id != target_id:
                continue
            fb = P.parse_feedback(f.data)
            if fb is not None:
                self._feedback = fb
                self._last_rx = time.monotonic()
                self._update_feedback_display()

    def _update_feedback_display(self):
        fb = self._feedback
        if fb is None:
            return

        self._fb_labels["position"].setText(f"{fb.position:+.2f}")
        self._fb_labels["speed"].setText(str(fb.speed))
        self._fb_labels["current"].setText(str(fb.current))
        self._fb_labels["temperature"].setText(f"{fb.temperature:.1f}")
        self._fb_labels["torque"].setText(
            f"{fb.torque:.2f}" if fb.torque is not None else _("Juxie.NoData"))
        self._fb_labels["error_code"].setText(f"0x{fb.error_code:04X}")
        self._fb_labels["mode_feedback"].setText(self._mode_name(fb.mode_feedback))

        if fb.error_code != 0:
            self._fb_labels["error_code"].setStyleSheet(f"color: {_ERR}; font-weight: 600;")
        else:
            self._fb_labels["error_code"].setStyleSheet(f"color: {_TEXT}; font-weight: 600;")

        status_parts = []
        status_parts.append(_("Juxie.Status.Enabled") if fb.enabled else _("Juxie.Status.Disabled"))
        status_parts.append(_("Juxie.Status.BrakeOff") if fb.brake_released else _("Juxie.Status.BrakeOn"))
        status_parts.append(_("Juxie.Status.Error") if fb.has_error else _("Juxie.Status.Normal"))
        status_parts.append(_("Juxie.Status.InPosition") if fb.position_reached else _("Juxie.Status.Running"))
        self._fb_status.setText("  |  ".join(status_parts))

        age = time.monotonic() - self._last_rx
        if age < 2.0:
            self._fb_update.setText(f"{_('Juxie.LastUpdate')}: {age:.1f}s")
            self._fb_update.setStyleSheet(f"color: {_OK};")
        else:
            self._fb_update.setText(_("Juxie.Offline"))
            self._fb_update.setStyleSheet(f"color: {_WARN};")

    def _mode_name(self, mode_val: int) -> str:
        name_map = {
            0x01: "Juxie.Mode.ProfilePos",
            0x02: "Juxie.Mode.ProfileVel",
            0x03: "Juxie.Mode.CSP",
            0x04: "Juxie.Mode.CSV",
            0x05: "Juxie.Mode.Current",
            0x06: "Juxie.Mode.Torque",
        }
        key = name_map.get(mode_val)
        return _(key) if key else f"0x{mode_val:02X}"

    # ── 生命周期 ──

    def on_activated(self):
        pass

    def on_deactivating(self):
        pass

    def on_connect(self):
        self._feedback = None
        self._clear_feedback_display()

    def on_disconnect(self):
        self._feedback = None
        self._clear_feedback_display()
        self._fb_update.setText(_("Juxie.Offline"))
        self._fb_update.setStyleSheet(f"color: {_WARN};")

    def _clear_feedback_display(self):
        for key in self._fb_labels:
            self._fb_labels[key].setText(_("Juxie.NoData"))
            self._fb_labels[key].setStyleSheet(f"color: {_TEXT}; font-weight: 600;")
        self._fb_status.setText("")
        self._fb_update.setText("")

    def refresh_language(self):
        self._update_id_label()
        self._update_pos_label()
        self._sync_btn.setText(_("Juxie.RequestFeedback"))
        self._send_btn.setText(_("Juxie.SendMIT"))
        self._enable_chk.setText(_("Juxie.Enable"))
        self._brake_chk.setText(_("Juxie.Brake"))
        self._clear_err_chk.setText(_("Juxie.ClearError"))
        self._auto_send_chk.setText(_("Juxie.AutoSend"))
        if self._feedback is not None:
            self._update_feedback_display()
