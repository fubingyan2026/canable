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

from canable_sdk import CANFrame
from . import protocol as P
from .upgrader import BootState, Upgrader

logger = logging.getLogger("plugin.boot_upgrade")


# i18n keys（运行时通过 ctx.register_i18n 注册）
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
    "Boot.Start":            ("开始升级",          "Start"),
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
    "Boot.CloseConfirm":     ("升级进行中，关闭 Tab 将发送 CANCEL。是否继续？",
                              "Upgrade in progress. Closing the tab will send CANCEL. Continue?"),
    "Boot.FDRequired":       ("所选帧长需 CAN FD 模式，请在主界面勾选 CAN FD",
                              "Selected frame size requires CAN FD mode. Enable CAN FD on the main panel."),

    # ---- upgrader 日志（plugin.py init 注册后 upgrader 通过 _() 获取）----
    "Boot.Log.NotConnected":  ("CAN 未连接，无法开始升级",
                                "CAN not connected, cannot start upgrade"),
    "Boot.Log.NoFirmware":    ("未配置固件", "Firmware not configured"),
    "Boot.Log.AlreadyActive": ("升级已在进行中", "Upgrade already in progress"),
    "Boot.Log.UserCancel":    ("用户取消", "Cancelled by user"),
    "Boot.Log.CancelSent":    ("→ CANCEL (用户取消)", "→ CANCEL (user cancel)"),
    "Boot.Log.CancelOnFail": ("→ CANCEL (失败后释放节点)", "→ CANCEL (release node on failure)"),
    "Boot.Log.NotConnectedSkip": ("未连接，跳过发送", "Not connected, skip send"),
    "Boot.Log.EarlyNack":    ("← 早 NACK: cmd=0x{:02X}, err=0x{:02X}, idx={}",
                              "← early NACK: cmd=0x{:02X}, err=0x{:02X}, idx={}"),
    "Boot.Log.UnexpectedAck":("← 非预期 ACK: cmd=0x{:02X} (期望 0x{:02X})",
                              "← unexpected ACK: cmd=0x{:02X} (expected 0x{:02X})"),
    "Boot.Log.AckTimeout":   ("等待 ACK 超时 (cmd={})",
                              "ACK wait timeout (cmd={})"),
    "Boot.Log.GlobalTimeout":("全局会话超时 (6s 无响应)",
                              "Global session timeout (6s no response)"),
    "Boot.Log.AckStart":     ("← ACK(START), 分区已擦除", "← ACK(START), partition erased"),
    "Boot.Log.AckMetadata":  ("← ACK(METADATA)", "← ACK(METADATA)"),
    "Boot.Log.AckDataStart": ("← ACK(DATA_START, block={})",
                              "← ACK(DATA_START, block={})"),
    "Boot.Log.AckDataEnd":   ("← ACK(DATA_END, block={})",
                              "← ACK(DATA_END, block={})"),
    "Boot.Log.AckVerify":    ("← ACK(VERIFY), 整包校验通过",
                              "← ACK(VERIFY), checksum passed"),
    "Boot.Log.AckReboot":    ("← ACK(REBOOT), 节点将复位",
                              "← ACK(REBOOT), node will reset"),
    "Boot.Log.AckCancel":    ("← ACK(CANCEL), 节点已退回 IDLE",
                              "← ACK(CANCEL), node back to IDLE"),
    "Boot.Log.NackBlockMismatch": ("← NACK(BLOCK_INDEX_MISMATCH, expected={})",
                                    "← NACK(BLOCK_INDEX_MISMATCH, expected={})"),
    "Boot.Log.NackBlockChecksum": ("← NACK(BLOCK_CHECKSUM, block={})",
                                    "← NACK(BLOCK_CHECKSUM, block={})"),
    "Boot.Log.StartFailed":  ("START 失败: err=0x{:02X} ({})",
                              "START failed: err=0x{:02X} ({})"),
    "Boot.Log.MetadataFailed": ("METADATA 失败: err=0x{:02X} ({})",
                                "METADATA failed: err=0x{:02X} ({})"),
    "Boot.Log.VerifyFailed": ("VERIFY 失败: err=0x{:02X} ({})",
                              "VERIFY failed: err=0x{:02X} ({})"),
    "Boot.Log.BlockRetryExceeded": ("块 {} 重试 {} 次仍失败",
                                     "Block {} retry {} times still failed"),
    "Boot.Log.BlockJumpExceeded": ("块号跳转重试 {} 次仍无法对齐",
                                    "Block index jump retry {} times still not aligned"),
    "Boot.Log.DataStartFailed": ("DATA_START 失败: err=0x{:02X}",
                                  "DATA_START failed: err=0x{:02X}"),
    "Boot.Log.DataEndFailed": ("DATA_END 失败: err=0x{:02X}",
                                "DATA_END failed: err=0x{:02X}"),
    "Boot.Log.BlockFailed":  ("块 {}: {}", "Block {}: {}"),
    "Boot.Log.Finished":     ("升级完成，等待节点重启",
                              "Upgrade complete, waiting for node reset"),
    "Boot.Log.Cancelled":    ("已取消", "Cancelled"),
    "Boot.Log.NotConnectedFinished": ("CAN not connected", "CAN not connected"),
    "Boot.Log.SendStart":    ("→ START: fw_size={}, hw_id=0x{:04X}, frame={}",
                                "→ START: fw_size={}, hw_id=0x{:04X}, frame={}"),
    "Boot.Log.SendMetadata": ("→ METADATA: checksum=0x{:08X}, version=0x{:04X}",
                                "→ METADATA: checksum=0x{:08X}, version=0x{:04X}"),
    "Boot.Log.SendDataStart": ("→ DATA_START: block={}", "→ DATA_START: block={}"),
    "Boot.Log.SendDataEnd":  ("→ DATA_END: seq={}, checksum=0x{:04X}, block={}, frames={}",
                                "→ DATA_END: seq={}, checksum=0x{:04X}, block={}, frames={}"),
    "Boot.Log.SendVerify":   ("→ VERIFY", "→ VERIFY"),
    "Boot.Log.SendReboot":   ("→ REBOOT", "→ REBOOT"),
}


# --------------------------------------------------------------------- #
#  配置持久化（统一存到主 settings.json，命名空间 plugin.boot_upgrade.*）
# --------------------------------------------------------------------- #
class _ConfigStore:
    """插件配置薄包装。复用 PluginContext 的 settings 读写能力。

    key 命名约定：`plugin.<plugin_name>.<field>`，由 PluginContext 自动加前缀。
    这里再叠一层 `boot_upgrade.` 前缀，避免与其他插件冲突。

    优点：
    - 与主程序设置统一落盘机制（2s 防抖、退出时立即写）
    - settings.json 一处管理全部状态，便于备份/迁移
    """

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
        # 类型校正：json 反序列化后 int 可能丢失
        if isinstance(default, int) and isinstance(v, (int, float)):
            return int(v)
        if isinstance(default, str) and not isinstance(v, str):
            return default
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)


# 状态显示文本
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
        self._upgrader = Upgrader(ctx)
        self._upgrader.state_changed.connect(self._on_state)
        self._upgrader.progress.connect(self._on_progress)
        self._upgrader.block_progress.connect(self._on_block_progress)
        self._upgrader.log.connect(self._on_log)
        self._upgrader.finished.connect(self._on_finished)
        self._build_ui()
        self._load_config_to_ui()
        # 加载完成后再绑信号，避免初始化时的 setValue 触发保存覆盖磁盘配置
        self._wire_config_save()
        self._refresh_state(BootState.IDLE)

    # ------------------------------------------------------------------ #
    #  UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # --- 配置区 ---
        self._cfg_box = QGroupBox(self._tr("Boot.Config"))
        cfg_layout = QFormLayout(self._cfg_box)

        self._file_edit = QLineEdit()
        self._file_edit.setReadOnly(True)
        self._browse_btn = QPushButton(self._tr("Boot.Browse"))
        self._browse_btn.clicked.connect(self._on_browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self._file_edit, 1)
        file_row.addWidget(self._browse_btn)
        # 显式 QLabel 以便 refresh_language 时更新文本
        # （QFormLayout.addRow(str, ...) 内部包成 QLabel 但无法外部访问）
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
        # 默认 64B（CAN FD）
        self._frame_size_combo.setCurrentIndex(
            self._frame_size_combo.findData(64))
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
        """重建帧长度下拉项（语言切换后调用）。
        保留当前选中项。
        """
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
        """从 _ConfigStore 恢复 UI 控件值。"""
        self._file_edit.setText(self._cfg.get("fw_path"))
        self._host_id_spin.setValue(int(self._cfg.get("host_id")))
        self._hw_id_spin.setValue(int(self._cfg.get("hw_id")))
        self._fw_version_spin.setValue(int(self._cfg.get("fw_version")))
        idx = self._frame_size_combo.findData(int(self._cfg.get("frame_size")))
        if idx >= 0:
            self._frame_size_combo.setCurrentIndex(idx)

    def _wire_config_save(self) -> None:
        """控件值变化时自动保存到 config.json（防抖 500ms）。"""
        self._host_id_spin.valueChanged.connect(
            lambda v: self._cfg.set("host_id", v))
        self._hw_id_spin.valueChanged.connect(
            lambda v: self._cfg.set("hw_id", v))
        self._fw_version_spin.valueChanged.connect(
            lambda v: self._cfg.set("fw_version", v))
        self._frame_size_combo.currentIndexChanged.connect(
            lambda i: self._cfg.set("frame_size",
                                     self._frame_size_combo.itemData(i)))
        # fw_path 在选择文件时保存（见 _on_browse）

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

        # 固件大小不在此校验：由节点侧 START 帧校验并回 NACK(FW_TOO_BIG)
        frame_size = self._frame_size_combo.currentData()
        # FD 帧长需主界面启用 CAN FD
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
        try:
            self._upgrader.configure(fw, version, hw_id, frame_size, host_id)
        except Exception as e:
            QMessageBox.critical(self, self._tr("Boot.Start"), str(e))
            return
        self._upgrader.start()

    def _on_cancel(self):
        if not self._upgrader.is_active:
            return
        if QMessageBox.question(self, self._tr("Boot.Cancel"),
                                self._tr("Boot.CancelConfirm")) != \
                QMessageBox.StandardButton.Yes:
            return
        self._upgrader.cancel()

    # ------------------------------------------------------------------ #
    #  Upgrader 信号处理
    # ------------------------------------------------------------------ #
    def _on_state(self, state: str):
        self._state_label.setText(
            f"{self._tr('Boot.State')}: {self._state_text(state)}")
        self._refresh_state(state)

    def _refresh_state(self, state: str):
        busy = state in (BootState.HANDSHAKE, BootState.TRANSFER,
                         BootState.VERIFY, BootState.REBOOT)
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

    # ------------------------------------------------------------------ #
    #  插件回调（由 plugin.py 转发）
    # ------------------------------------------------------------------ #
    def on_connect(self):
        pass

    def on_disconnect(self):
        if self._upgrader.is_active:
            self._upgrader.cancel()

    def on_frames(self, frames):
        for f in frames:
            self._upgrader.on_frame(f)

    def refresh_language(self):
        # 重新设置所有可见文本
        self._cfg_box.setTitle(self._tr("Boot.Config"))
        self._prog_box.setTitle(self._tr("Boot.Progress"))
        self._log_box.setTitle(self._tr("Boot.Log"))
        self._browse_btn.setText(self._tr("Boot.Browse"))
        self._start_btn.setText(self._tr("Boot.Start"))
        self._cancel_btn.setText(self._tr("Boot.Cancel"))
        # 表单行标签（需要 refresh 时刷新）
        self._lbl_firmware_file.setText(self._tr("Boot.FirmwareFile"))
        self._lbl_host_can_id.setText(self._tr("Boot.HostCanID"))
        self._lbl_hardware_id.setText(self._tr("Boot.HardwareID"))
        self._lbl_firmware_version.setText(self._tr("Boot.FirmwareVersion"))
        self._lbl_frame_size.setText(self._tr("Boot.FrameSize"))
        # 进度区子标签
        self._block_label.setText(self._tr("Boot.BlockProgress"))
        self._overall_label.setText(self._tr("Boot.OverallProgress"))
        # 帧长度下拉项
        self._rebuild_frame_size_combo()
        # 状态标签
        self._state_label.setText(
            f"{self._tr('Boot.State')}: {self._state_text(self._upgrader.state)}")

    def confirm_close(self) -> bool:
        """Tab 关闭前确认。返回 False 表示阻止关闭。"""
        if not self._upgrader.is_active:
            return True
        ret = QMessageBox.question(self, self._tr("Boot.Cancel"),
                                   self._tr("Boot.CloseConfirm"))
        return ret == QMessageBox.StandardButton.Yes
