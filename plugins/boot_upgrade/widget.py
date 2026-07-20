"""Boot 升级 UI 面板。

布局：
    ┌─────────────────────────────────────────────┐
    │ 配置区  (固件文件 / CAN ID / HW ID / 版本 / 帧长)│
    ├─────────────────────────────────────────────┤
    │ 进度区  (块进度条 / 总进度条 / 当前状态)         │
    ├─────────────────────────────────────────────┤
    │ 操作区  (开始 / 取消)                          │
    ├─────────────────────────────────────────────┤
    │ 日志区  (协议交互文本)                          │
    └─────────────────────────────────────────────┘

升级期间 UpgradeTask 在宿主 CAN worker 线程上运行，直接操作已打开的 ZDTCanable
（帧间 1ms 节流 + 中途 NACK 拦截，对齐 flash_tool）。
插件不管理设备生命周期，只负责数据收发。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGroupBox,
                                QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                                QPlainTextEdit, QProgressBar, QPushButton,
                                QSpinBox, QVBoxLayout, QWidget)

from . import protocol as P
from .upgrader import UpgradeTask, UpgradeSignals, BootConfig

logger = logging.getLogger("plugin.boot_upgrade")

# ── 状态常量 ──
class BootState:
    IDLE = "idle"
    HANDSHAKE = "handshake"
    TRANSFER = "transfer"
    VERIFY = "verify"
    REBOOT = "reboot"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATES = (BootState.HANDSHAKE, BootState.TRANSFER,
                 BootState.VERIFY, BootState.REBOOT)


_I18N_KEYS = {
    "Boot.Title":            ("Boot 升级",        "Boot Upgrade"),
    "Boot.Config":           ("配置",             "Configuration"),
    "Boot.FirmwareFile":     ("固件文件",          "Firmware File"),
    "Boot.Browse":           ("浏览…",            "Browse…"),
    "Boot.HostCanID":        ("主机 CAN ID",       "Host CAN ID"),
    "Boot.HardwareID":       ("硬件兼容 ID",       "Hardware ID"),
    "Boot.FirmwareVersion":  ("固件版本",          "Firmware Version"),
    "Boot.FrameSize":        ("帧长度",           "Frame Size"),
    "Boot.Progress":         ("进度",             "Progress"),
    "Boot.BlockProgress":    ("当前块进度",        "Block Progress"),
    "Boot.OverallProgress":  ("总进度",           "Overall"),
    "Boot.State":            ("状态",             "State"),
    "Boot.Start":            ("开始升级",          "Start Upgrade"),
    "Boot.Cancel":           ("取消升级",          "Cancel"),
    "Boot.Log":              ("日志",             "Log"),
    "Boot.SelectFirmware":    ("选择固件文件",      "Select Firmware File"),
    "Boot.FirmwareFilter":   ("固件 (*.bin *.hex);;所有文件 (*)",
                              "Firmware (*.bin *.hex);;All files (*)"),
    "Boot.NotConnected":     ("CAN 未连接，请先在主界面连接设备",
                              "CAN not connected. Connect a device first."),
    "Boot.NoFile":           ("请先选择固件文件",   "Please select a firmware file first."),
    "Boot.StartConfirm":     ("确认开始升级？\n\n固件: {}\n大小: {} 字节\n版本: 0x{:04X}\n硬件 ID: 0x{:04X}\n帧长: {}",
                              "Start upgrade?\n\nFirmware: {}\nSize: {} bytes\nVersion: 0x{:04X}\nHW ID: 0x{:04X}\nFrame: {}"),
    "Boot.CancelConfirm":    ("升级进行中，确认取消？",
                              "Upgrade in progress. Cancel?"),
    "Boot.Done":             ("升级完成",          "Upgrade complete"),
    "Boot.LoadFailed":       ("读取固件失败: {}",
                              "Failed to read firmware: {}"),
    "Boot.CloseConfirm":     ("升级进行中，关闭 Tab 将取消升级。是否继续？",
                              "Upgrade in progress. Closing the tab will cancel. Continue?"),
    "Boot.FDRequired":       ("所选帧长需 CAN FD 模式，请在主界面勾选 CAN FD",
                              "Selected frame size requires CAN FD mode. Enable CAN FD on the main panel."),
    "Boot.Cancelling":       ("取消中…", "Cancelling…"),
    "Boot.ClearLog":         ("清空日志", "Clear Log"),
}


class _ConfigStore:
    PLUGIN_NAME = "boot_upgrade"

    DEFAULTS = {
        "fw_path":      "",
        "host_id":      P.DEFAULT_HOST_ID,
        "hw_id":        0x0001,
        "fw_version":   0x0100,
        "frame_size":   64,
    }

    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        v = self._ctx.get_setting(f"{self.PLUGIN_NAME}.{key}", default)
        if isinstance(default, int) and isinstance(v, (int, float)):
            return int(v)
        if isinstance(default, str) and not isinstance(v, str):
            return default
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


_STATE_TEXT_ZH = {
    BootState.IDLE:       "空闲",
    BootState.HANDSHAKE:  "握手中",
    BootState.TRANSFER:   "传输中",
    BootState.VERIFY:     "校验中",
    BootState.REBOOT:     "复位中",
    BootState.DONE:       "完成",
    BootState.FAILED:     "失败",
    BootState.CANCELLED:  "已取消",
}

_STATE_TEXT_EN = {
    BootState.IDLE:       "Idle",
    BootState.HANDSHAKE:  "Handshake",
    BootState.TRANSFER:   "Transferring",
    BootState.VERIFY:     "Verifying",
    BootState.REBOOT:     "Rebooting",
    BootState.DONE:       "Done",
    BootState.FAILED:     "Failed",
    BootState.CANCELLED:  "Cancelled",
}


class BootUpgradePanel(QWidget):
    """Boot 升级面板。"""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._cfg = _ConfigStore(ctx)
        self._task: Optional[UpgradeTask] = None
        self._signals: Optional[UpgradeSignals] = None
        self._current_state = BootState.IDLE
        self._build_ui()
        self._load_config_to_ui()
        self._wire_config_save()
        self._refresh_state(BootState.IDLE)

    # ------------------------------------------------------------------ #
    #  UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._cfg_box = QGroupBox(self._tr("Boot.Config"))
        cfg_layout = QFormLayout(self._cfg_box)

        self._file_edit = QLineEdit()
        self._file_edit.setReadOnly(True)
        self._browse_btn = QPushButton(self._tr("Boot.Browse"))
        self._browse_btn.clicked.connect(self._on_browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self._file_edit, 1)
        file_row.addWidget(self._browse_btn)
        self._lbl_firmware_file = QLabel(self._tr("Boot.FirmwareFile"))
        cfg_layout.addRow(self._lbl_firmware_file, file_row)

        self._host_id_spin = QSpinBox()
        self._host_id_spin.setRange(0, 0x7FF)
        self._host_id_spin.setValue(P.DEFAULT_HOST_ID)
        self._host_id_spin.setDisplayIntegerBase(16)
        self._host_id_spin.setPrefix("0x")
        self._lbl_host_can_id = QLabel(self._tr("Boot.HostCanID"))
        cfg_layout.addRow(self._lbl_host_can_id, self._host_id_spin)

        self._hw_id_spin = QSpinBox()
        self._hw_id_spin.setRange(0, 0xFFFF)
        self._hw_id_spin.setValue(0x0001)
        self._hw_id_spin.setDisplayIntegerBase(16)
        self._hw_id_spin.setPrefix("0x")
        self._lbl_hardware_id = QLabel(self._tr("Boot.HardwareID"))
        cfg_layout.addRow(self._lbl_hardware_id, self._hw_id_spin)

        self._fw_version_spin = QSpinBox()
        self._fw_version_spin.setRange(0, 0xFFFF)
        self._fw_version_spin.setValue(0x0100)
        self._fw_version_spin.setDisplayIntegerBase(16)
        self._fw_version_spin.setPrefix("0x")
        self._lbl_firmware_version = QLabel(self._tr("Boot.FirmwareVersion"))
        cfg_layout.addRow(self._lbl_firmware_version, self._fw_version_spin)

        self._frame_size_combo = QComboBox()
        self._rebuild_frame_size_combo()
        self._frame_size_combo.setCurrentIndex(self._frame_size_combo.findData(64))
        self._lbl_frame_size = QLabel(self._tr("Boot.FrameSize"))
        cfg_layout.addRow(self._lbl_frame_size, self._frame_size_combo)

        layout.addWidget(self._cfg_box)

        # --- 进度区 ---
        self._prog_box = QGroupBox(self._tr("Boot.Progress"))
        prog_layout = QVBoxLayout(self._prog_box)

        self._block_bar = QProgressBar()
        self._block_bar.setRange(0, 100)
        self._block_label = QLabel(self._tr("Boot.BlockProgress"))
        prog_layout.addWidget(self._block_label)
        prog_layout.addWidget(self._block_bar)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        self._overall_label = QLabel(self._tr("Boot.OverallProgress"))
        prog_layout.addWidget(self._overall_label)
        prog_layout.addWidget(self._overall_bar)

        self._state_label = QLabel(
            f"{self._tr('Boot.State')}: {self._state_text(BootState.IDLE)}")
        prog_layout.addWidget(self._state_label)

        layout.addWidget(self._prog_box)

        # --- 控制按钮 ---
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton(self._tr("Boot.Start"))
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.clicked.connect(self._on_start)
        self._cancel_btn = QPushButton(self._tr("Boot.Cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        btn_row.addStretch(1)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        # --- 日志区 ---
        self._log_box = QGroupBox(self._tr("Boot.Log"))
        log_layout = QVBoxLayout(self._log_box)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self._log_view.setFont(font)
        log_layout.addWidget(self._log_view)
        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        self._clear_log_btn = QPushButton(self._tr("Boot.ClearLog"))
        self._clear_log_btn.clicked.connect(self._log_view.clear)
        clear_row.addWidget(self._clear_log_btn)
        log_layout.addLayout(clear_row)
        layout.addWidget(self._log_box, 1)

    # ------------------------------------------------------------------ #
    #  i18n / 状态文本
    # ------------------------------------------------------------------ #
    def _tr(self, key: str) -> str:
        from cangui.i18n import _
        return _(key)

    def _state_text(self, state: str) -> str:
        from cangui.i18n import get_language
        table = _STATE_TEXT_ZH if get_language() == "zh" else _STATE_TEXT_EN
        return table.get(state, state)

    def _rebuild_frame_size_combo(self) -> None:
        current_data = self._frame_size_combo.currentData() if hasattr(self, "_frame_size_combo") else 64
        self._frame_size_combo.blockSignals(True)
        self._frame_size_combo.clear()
        for sz in P.SUPPORTED_FRAME_SIZES:
            suffix = " (Classic CAN)" if sz == 8 else f" (CAN FD)"
            self._frame_size_combo.addItem(f"{sz}B{suffix}", sz)
        idx = self._frame_size_combo.findData(current_data)
        if idx >= 0:
            self._frame_size_combo.setCurrentIndex(idx)
        self._frame_size_combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  配置持久化
    # ------------------------------------------------------------------ #
    def _load_config_to_ui(self) -> None:
        self._file_edit.setText(self._cfg.get("fw_path"))
        self._host_id_spin.setValue(int(self._cfg.get("host_id")))
        self._hw_id_spin.setValue(int(self._cfg.get("hw_id")))
        self._fw_version_spin.setValue(int(self._cfg.get("fw_version")))
        idx = self._frame_size_combo.findData(int(self._cfg.get("frame_size")))
        if idx >= 0:
            self._frame_size_combo.setCurrentIndex(idx)

    def _wire_config_save(self) -> None:
        self._host_id_spin.valueChanged.connect(
            lambda v: self._cfg.set("host_id", v))
        self._hw_id_spin.valueChanged.connect(
            lambda v: self._cfg.set("hw_id", v))
        self._fw_version_spin.valueChanged.connect(
            lambda v: self._cfg.set("fw_version", v))
        self._frame_size_combo.currentIndexChanged.connect(
            lambda i: self._cfg.set("frame_size",
                                     self._frame_size_combo.itemData(i)))

    # ------------------------------------------------------------------ #
    #  按钮事件
    # ------------------------------------------------------------------ #
    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("Boot.SelectFirmware"), "",
            self._tr("Boot.FirmwareFilter"))
        if path:
            self._file_edit.setText(path)
            self._cfg.set("fw_path", path)

    def _on_start(self):
        if not self._ctx.is_connected():
            QMessageBox.warning(self, self._tr("Boot.Start"),
                                self._tr("Boot.NotConnected"))
            return
        path = self._file_edit.text().strip()
        if not path:
            QMessageBox.warning(self, self._tr("Boot.Start"),
                                self._tr("Boot.NoFile"))
            return
        try:
            with open(path, "rb") as f:
                fw = f.read()
        except Exception as e:
            QMessageBox.critical(self, self._tr("Boot.Start"),
                                 self._tr("Boot.LoadFailed").format(e))
            return

        frame_size = self._frame_size_combo.currentData()
        if frame_size > 8 and not self._ctx.is_fd_mode():
            QMessageBox.warning(self, self._tr("Boot.Start"),
                                self._tr("Boot.FDRequired"))
            return

        version = self._fw_version_spin.value()
        hw_id = self._hw_id_spin.value()
        host_id = self._host_id_spin.value()

        confirm = self._tr("Boot.StartConfirm").format(
            os.path.basename(path), len(fw), version, hw_id, frame_size)
        if QMessageBox.question(self, self._tr("Boot.Start"), confirm) != \
                QMessageBox.StandardButton.Yes:
            return

        self._log_view.clear()
        self._block_bar.setValue(0)
        self._overall_bar.setValue(0)

        config = BootConfig(
            fw=fw, fw_version=version, hw_id=hw_id,
            max_frame_size=frame_size, host_id=host_id,
        )

        self._signals = UpgradeSignals()
        self._signals.state_changed.connect(self._on_state)
        self._signals.progress.connect(self._on_progress)
        self._signals.block_progress.connect(self._on_block_progress)
        self._signals.log.connect(self._on_log)
        self._signals.finished.connect(self._on_finished)

        self._task = UpgradeTask(config, self._signals)
        self._ctx.start_upgrade(self._task)

    def _on_cancel(self):
        if self._task is None:
            return
        if QMessageBox.question(self, self._tr("Boot.Cancel"),
                                self._tr("Boot.CancelConfirm")) != \
                QMessageBox.StandardButton.Yes:
            return
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText(self._tr("Boot.Cancelling"))
        self._task.cancel()

    # ------------------------------------------------------------------ #
    #  信号处理
    # ------------------------------------------------------------------ #
    def _on_state(self, state: str):
        self._current_state = state
        self._state_label.setText(
            f"{self._tr('Boot.State')}: {self._state_text(state)}")
        self._refresh_state(state)

    def _refresh_state(self, state: str):
        busy = state in ACTIVE_STATES
        self._start_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._browse_btn.setEnabled(not busy)
        self._host_id_spin.setEnabled(not busy)
        self._hw_id_spin.setEnabled(not busy)
        self._fw_version_spin.setEnabled(not busy)
        self._frame_size_combo.setEnabled(not busy)

    def _on_progress(self, block: int, total: int):
        pct = int(block * 100 / total) if total > 0 else 0
        self._overall_bar.setValue(pct)

    def _on_block_progress(self, frame: int, total: int):
        pct = int(frame * 100 / total) if total > 0 else 0
        self._block_bar.setValue(pct)

    def _on_log(self, level: str, msg: str):
        prefix = {"info": "", "warn": "⚠ ", "error": "✗ "}.get(level, "")
        self._log_view.appendPlainText(f"{prefix}{msg}")

    def _on_finished(self, success: bool, msg: str):
        if success:
            self._log_view.appendPlainText(f"\n✓ {self._tr('Boot.Done')}: {msg}")
        else:
            self._log_view.appendPlainText(f"\n✗ {msg}")

        self._task = None
        self._signals = None
        self._cancel_btn.setText(self._tr("Boot.Cancel"))
        self._refresh_state(BootState.DONE if success else BootState.FAILED)

    # ------------------------------------------------------------------ #
    #  插件回调
    # ------------------------------------------------------------------ #
    def on_connect(self):
        pass

    def on_disconnect(self):
        pass

    def on_frames(self, frames):
        pass  # Upgrader 在 worker 线程直接收发，不依赖宿主派发

    def refresh_language(self):
        self._cfg_box.setTitle(self._tr("Boot.Config"))
        self._prog_box.setTitle(self._tr("Boot.Progress"))
        self._log_box.setTitle(self._tr("Boot.Log"))
        self._browse_btn.setText(self._tr("Boot.Browse"))
        self._start_btn.setText(self._tr("Boot.Start"))
        if self._task is None:
            self._cancel_btn.setText(self._tr("Boot.Cancel"))
        self._lbl_firmware_file.setText(self._tr("Boot.FirmwareFile"))
        self._lbl_host_can_id.setText(self._tr("Boot.HostCanID"))
        self._lbl_hardware_id.setText(self._tr("Boot.HardwareID"))
        self._lbl_firmware_version.setText(self._tr("Boot.FirmwareVersion"))
        self._lbl_frame_size.setText(self._tr("Boot.FrameSize"))
        self._block_label.setText(self._tr("Boot.BlockProgress"))
        self._overall_label.setText(self._tr("Boot.OverallProgress"))
        self._clear_log_btn.setText(self._tr("Boot.ClearLog"))
        self._rebuild_frame_size_combo()
        self._state_label.setText(
            f"{self._tr('Boot.State')}: {self._state_text(self._current_state)}")

    def confirm_close(self) -> bool:
        if self._task is None:
            return True
        ret = QMessageBox.question(self, self._tr("Boot.Cancel"),
                                   self._tr("Boot.CloseConfirm"))
        return ret == QMessageBox.StandardButton.Yes
