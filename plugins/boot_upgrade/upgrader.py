"""Bootloader 升级状态机（主机端）。

实现 boot_protocol_spec.md §5 升级流程与 §6 错误处理：

状态流转::

    IDLE → HANDSHAKE → TRANSFER → VERIFY → REBOOT → DONE
                       ↓            ↓
                     FAILED       FAILED

设计要点：
- 通过 PluginContext.send_frame() 走 worker 线程安全队列发送
- 通过 on_frame() 接收节点 ACK/NACK（由插件 on_frames 派发）
- QTimer 实现 ACK 等待与全局超时
- 断点续传：DATA_START NACK(BLOCK_INDEX_MISMATCH) 时跳到期望块号
- 同块最多重试 MAX_RETRIES 次

注：本状态机运行在主线程，所有 Qt 信号/定时器均可直接使用。
"""
from __future__ import annotations

import logging
from typing import Optional, List

from PySide6.QtCore import QObject, QTimer, Signal

from canable_sdk import CANFrame
from cangui.i18n import _
from . import protocol as P
from .protocol import Cmd, Err

logger = logging.getLogger("plugin.boot_upgrade")


class BootState:
    IDLE = "idle"
    HANDSHAKE = "handshake"
    TRANSFER = "transfer"
    VERIFY = "verify"
    REBOOT = "reboot"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 处于这些状态时表示升级"进行中"，关闭 Tab / 断开连接应触发 CANCEL
ACTIVE_STATES = (BootState.HANDSHAKE, BootState.TRANSFER,
                  BootState.VERIFY, BootState.REBOOT)


class Upgrader(QObject):
    """主机端 Bootloader 状态机。

    信号：
        state_changed(str)      — 状态变化
        progress(int, int)      — (已完成块数, 总块数)
        block_progress(int,int) — (块内已发帧数, 块内总帧数)
        log(str, str)           — (level, message)  level: info/warn/error
        finished(bool, str)     — (success, message)
    """

    state_changed = Signal(str)
    progress = Signal(int, int)
    block_progress = Signal(int, int)
    log = Signal(str, str)
    finished = Signal(bool, str)

    def __init__(self, ctx):
        super().__init__()
        self._ctx = ctx
        self._fw: Optional[bytes] = None
        self._fw_version: int = 0
        self._hw_id: int = 0
        self._max_frame_size: int = 64
        self._host_id: int = P.DEFAULT_HOST_ID
        self._node_id: int = P.DEFAULT_NODE_ID

        self._state = BootState.IDLE
        self._expected_block = 0
        self._total_blocks = 0
        self._retries = 0

        # 请求-响应配对
        self._pending_ack_cmd: Optional[int] = None

        # ACK 等待定时器（每命令一个）
        self._ack_timer = QTimer(self)
        self._ack_timer.setSingleShot(True)
        self._ack_timer.timeout.connect(self._on_ack_timeout)

        # 全局会话超时（6s 无响应 → 失败）
        self._global_timer = QTimer(self)
        self._global_timer.setSingleShot(True)
        self._global_timer.timeout.connect(self._on_global_timeout)

    # ------------------------------------------------------------------ #
    #  属性
    # ------------------------------------------------------------------ #
    @property
    def state(self) -> str:
        return self._state

    @property
    def node_id(self) -> int:
        return self._node_id

    @property
    def host_id(self) -> int:
        return self._host_id

    @property
    def is_active(self) -> bool:
        """升级进行中（用于插件判断是否需阻止关闭）。"""
        return self._state in ACTIVE_STATES

    # ------------------------------------------------------------------ #
    #  配置
    # ------------------------------------------------------------------ #
    def configure(self, fw: bytes, fw_version: int, hw_id: int,
                  max_frame_size: int, host_id: int) -> None:
        if max_frame_size not in P.SUPPORTED_FRAME_SIZES:
            raise ValueError(f"frame_size {max_frame_size} not in {P.SUPPORTED_FRAME_SIZES}")
        # 固件大小由用户自行负责：节点侧会校验 fw_size ≤ App 分区并回 NACK(FW_TOO_BIG)
        self._fw = fw
        self._fw_version = fw_version & 0xFFFF
        self._hw_id = hw_id & 0xFFFF
        self._max_frame_size = max_frame_size
        self._host_id = host_id & 0x7FF  # 标准帧
        self._node_id = (host_id + 1) & 0x7FF
        self._total_blocks = P.total_blocks(len(fw))

    # ------------------------------------------------------------------ #
    #  启动 / 取消
    # ------------------------------------------------------------------ #
    def start(self) -> bool:
        if not self._ctx.is_connected():
            self._emit_log("error", _("Boot.Log.NotConnected"))
            self._set_state(BootState.FAILED)
            self.finished.emit(False, _("Boot.Log.NotConnectedFinished"))
            return False
        if not self._fw:
            self._emit_log("error", _("Boot.Log.NoFirmware"))
            return False
        if self._state in ACTIVE_STATES:
            self._emit_log("warn", _("Boot.Log.AlreadyActive"))
            return False

        self._set_state(BootState.HANDSHAKE)
        self._global_timer.start(P.GLOBAL_TIMEOUT_MS)
        self._expected_block = 0
        self._retries = 0
        self.progress.emit(0, self._total_blocks)
        return self._send_start()

    def cancel(self) -> None:
        """用户主动取消。无论当前状态都发送 CANCEL 并复位。"""
        if self._state in (BootState.IDLE, BootState.DONE,
                           BootState.FAILED, BootState.CANCELLED):
            self._set_state(BootState.CANCELLED)
            self.finished.emit(False, _("Boot.Log.UserCancel"))
            return
        self._emit_log("info", _("Boot.Log.CancelSent"))
        try:
            self._send_frame(build_cancel_payload(), fd=False, force=False)
        except Exception as e:
            logger.warning("CANCEL 发送失败: %s", e)
        self._ack_timer.stop()
        self._global_timer.stop()
        self._pending_ack_cmd = None
        self._set_state(BootState.CANCELLED)
        self.finished.emit(False, _("Boot.Log.UserCancel"))

    def reset(self) -> None:
        """复位到 IDLE（不发送任何帧）。"""
        self._ack_timer.stop()
        self._global_timer.stop()
        self._pending_ack_cmd = None
        self._expected_block = 0
        self._retries = 0
        self._set_state(BootState.IDLE)

    # ------------------------------------------------------------------ #
    #  帧接收（由插件 on_frames 调用）
    # ------------------------------------------------------------------ #
    def on_frame(self, frame: CANFrame) -> None:
        if frame.can_id != self._node_id:
            return
        if getattr(frame, "is_tx", False):
            return  # 忽略自己的 TX echo
        # 取 DLC 范围内数据
        dlc = getattr(frame, "dlc", len(frame.data))
        raw = bytes(frame.data[:dlc]) if dlc <= len(frame.data) else bytes(frame.data)
        ack = P.parse_response(raw)
        if ack is None:
            return

        # 收到任何响应，重置全局超时
        if self._state in ACTIVE_STATES:
            self._global_timer.start(P.GLOBAL_TIMEOUT_MS)

        # 不在等待任何 ACK
        if self._pending_ack_cmd is None:
            if not ack.is_ack:
                self._emit_log("warn",
                               _("Boot.Log.EarlyNack").format(
                                   ack.acked_cmd, ack.status, ack.block_index))
            return

        # 命令字不匹配
        if ack.acked_cmd != self._pending_ack_cmd:
            self._emit_log("warn",
                           _("Boot.Log.UnexpectedAck").format(
                               ack.acked_cmd, self._pending_ack_cmd))
            return

        self._ack_timer.stop()
        expected_cmd = self._pending_ack_cmd
        self._pending_ack_cmd = None

        # 分发到对应处理器
        handler = {
            Cmd.START:      self._on_start_ack,
            Cmd.METADATA:   self._on_metadata_ack,
            Cmd.DATA_START: self._on_data_start_ack,
            Cmd.DATA_END:   self._on_data_end_ack,
            Cmd.VERIFY:     self._on_verify_ack,
            Cmd.REBOOT:     self._on_reboot_ack,
            Cmd.CANCEL:     self._on_cancel_ack,
        }.get(expected_cmd)
        if handler:
            handler(ack)

    # ------------------------------------------------------------------ #
    #  命令发送
    # ------------------------------------------------------------------ #
    def _send_frame(self, payload: bytes, fd: bool = False, force: bool = False) -> None:
        """构造 CANFrame 并经 ctx 发送。

        Args:
            payload: 帧数据（含 Cmd/Seq/Payload）
            fd:      是否使用 CAN FD（True 时同时置 BRS）
            force:   True 时即使未连接也尝试（用于 CANCEL 等）
        """
        if not force and not self._ctx.is_connected():
            self._emit_log("warn", _("Boot.Log.NotConnectedSkip"))
            return
        frame = CANFrame(can_id=self._host_id, data=payload,
                         extended=False, fd=fd)
        if fd:
            frame.brs = True
        self._ctx.send_frame(frame)

    def _wait_ack(self, cmd: int, timeout_ms: int = P.BLOCK_ACK_TIMEOUT_MS) -> None:
        """设置待 ACK 命令字。必须在 _send_frame 之后调用，避免 timer 起点早于实际发送。"""
        self._pending_ack_cmd = cmd
        self._ack_timer.start(timeout_ms)

    # ---- 各命令构造 ---- #
    def _send_start(self) -> bool:
        payload = P.build_start(len(self._fw), self._hw_id, self._max_frame_size)
        self._emit_log("info",
                        _("Boot.Log.SendStart").format(
                            len(self._fw), self._hw_id, self._max_frame_size))
        self._send_frame(payload, fd=False)  # START 固定 8 字节经典 CAN
        self._wait_ack(Cmd.START, 2000)
        return True

    def _send_metadata(self) -> None:
        cs = P.calc_32bit_checksum(self._fw)
        payload = P.build_metadata(cs, self._fw_version)
        self._emit_log("info",
                       _("Boot.Log.SendMetadata").format(cs, self._fw_version))
        self._send_frame(payload, fd=False)
        self._wait_ack(Cmd.METADATA, 2000)

    def _send_block(self, block_index: int) -> None:
        """发送 DATA_START + 所有 DATA + DATA_END。"""
        # 1) DATA_START（固定 8B 经典 CAN）
        ds = P.build_data_start(block_index)
        self._emit_log("info", _("Boot.Log.SendDataStart").format(block_index))
        self._send_frame(ds, fd=False)
        self._wait_ack(Cmd.DATA_START, 1000)

    def _send_data_frames(self, block_index: int) -> None:
        """收到 DATA_START ACK 后，发送该块的全部 DATA + DATA_END。"""
        start = block_index * P.BLOCK_SIZE
        end = min(start + P.BLOCK_SIZE, len(self._fw))
        block = self._fw[start:end]
        if len(block) < P.BLOCK_SIZE:
            block = block + bytes(P.BLOCK_SIZE - len(block))

        # 拆分
        data_frames, end_seq, end_remaining = P.split_block(block, self._max_frame_size)
        total_frames = len(data_frames) + 1
        use_fd = self._max_frame_size > 8

        # 2) DATA 帧序列（无 ACK）
        for i, (seq, payload) in enumerate(data_frames):
            data = P.build_data(seq, payload)
            self._send_frame(data, fd=use_fd)
            self.block_progress.emit(i + 1, total_frames)

        # 3) DATA_END（含 16-bit checksum + remaining）
        cs = P.calc_16bit_checksum(block)
        end_payload = P.build_data_end(end_seq, cs, end_remaining)
        # CAN FD DLC 离散填充：不足时零填充到 max_frame_size
        if use_fd and len(end_payload) < self._max_frame_size:
            end_payload = end_payload + bytes(self._max_frame_size - len(end_payload))
        self._emit_log("info",
                       _("Boot.Log.SendDataEnd").format(
                           end_seq, cs, block_index, total_frames))
        self._send_frame(end_payload, fd=use_fd)
        self._wait_ack(Cmd.DATA_END, 2000)

    def _send_verify(self) -> None:
        self._emit_log("info", _("Boot.Log.SendVerify"))
        self._send_frame(P.build_verify(), fd=False)
        self._wait_ack(Cmd.VERIFY, 3000)

    def _send_reboot(self) -> None:
        self._emit_log("info", _("Boot.Log.SendReboot"))
        self._send_frame(P.build_reboot(), fd=False)
        self._wait_ack(Cmd.REBOOT, 2000)

    # ------------------------------------------------------------------ #
    #  ACK 处理
    # ------------------------------------------------------------------ #
    def _on_start_ack(self, ack: P.AckInfo) -> None:
        if not ack.ok:
            self._fail(_("Boot.Log.StartFailed").format(ack.status, _err_name(ack.status)))
            return
        self._emit_log("info", _("Boot.Log.AckStart"))
        self._send_metadata()

    def _on_metadata_ack(self, ack: P.AckInfo) -> None:
        if not ack.ok:
            self._fail(_("Boot.Log.MetadataFailed").format(ack.status, _err_name(ack.status)))
            return
        self._emit_log("info", _("Boot.Log.AckMetadata"))
        self._set_state(BootState.TRANSFER)
        self._expected_block = 0
        self._retries = 0
        self._send_block(0)

    def _on_data_start_ack(self, ack: P.AckInfo) -> None:
        if ack.ok:
            self._emit_log("info",
                           _("Boot.Log.AckDataStart").format(ack.block_index))
            self._send_data_frames(self._expected_block)
        elif ack.status == P.Err.BLOCK_INDEX_MISMATCH:
            # 节点期望不同块号，跳转续传
            self._emit_log("warn",
                           _("Boot.Log.NackBlockMismatch").format(ack.block_index))
            # 续传也递增重试计数，防止异常节点诱导无限循环
            self._retries += 1
            if self._retries > P.MAX_RETRIES:
                self._fail_block(_("Boot.Log.BlockJumpExceeded").format(P.MAX_RETRIES))
                return
            self._expected_block = ack.block_index
            self._send_block(self._expected_block)
        else:
            self._fail_block(_("Boot.Log.DataStartFailed").format(ack.status))

    def _on_data_end_ack(self, ack: P.AckInfo) -> None:
        if ack.ok:
            self._emit_log("info",
                           _("Boot.Log.AckDataEnd").format(self._expected_block))
            self._retries = 0
            self._expected_block += 1
            self.progress.emit(self._expected_block, self._total_blocks)
            if self._expected_block >= self._total_blocks:
                self._set_state(BootState.VERIFY)
                self._send_verify()
            else:
                self._send_block(self._expected_block)
        elif ack.status == P.Err.BLOCK_CHECKSUM:
            self._emit_log("warn",
                           _("Boot.Log.NackBlockChecksum").format(self._expected_block))
            self._retries += 1
            if self._retries > P.MAX_RETRIES:
                self._fail_block(_("Boot.Log.BlockRetryExceeded").format(
                    self._expected_block, P.MAX_RETRIES))
            else:
                self._send_block(self._expected_block)
        else:
            self._fail_block(_("Boot.Log.DataEndFailed").format(ack.status))

    def _on_verify_ack(self, ack: P.AckInfo) -> None:
        if not ack.ok:
            self._fail(_("Boot.Log.VerifyFailed").format(ack.status, _err_name(ack.status)))
            return
        self._emit_log("info", _("Boot.Log.AckVerify"))
        self._set_state(BootState.REBOOT)
        self._send_reboot()

    def _on_reboot_ack(self, ack: P.AckInfo) -> None:
        self._emit_log("info", _("Boot.Log.AckReboot"))
        self._global_timer.stop()
        self._set_state(BootState.DONE)
        self.finished.emit(True, _("Boot.Log.Finished"))

    def _on_cancel_ack(self, ack: P.AckInfo) -> None:
        self._emit_log("info", _("Boot.Log.AckCancel"))
        self._global_timer.stop()
        self._set_state(BootState.CANCELLED)
        self.finished.emit(False, _("Boot.Log.Cancelled"))

    # ------------------------------------------------------------------ #
    #  超时处理
    # ------------------------------------------------------------------ #
    def _on_ack_timeout(self) -> None:
        cmd = self._pending_ack_cmd
        self._pending_ack_cmd = None
        cmd_str = f"0x{cmd:02X}" if cmd is not None else "None"
        self._fail(_("Boot.Log.AckTimeout").format(cmd_str))

    def _on_global_timeout(self) -> None:
        self._ack_timer.stop()
        self._pending_ack_cmd = None
        self._fail(_("Boot.Log.GlobalTimeout"))

    # ------------------------------------------------------------------ #
    #  失败处理
    # ------------------------------------------------------------------ #
    def _fail(self, msg: str) -> None:
        """升级失败：停定时器 + 尝试发 CANCEL 释放节点状态 + emit finished。

        规范 §5.4：上位机会话终止应发送 CANCEL，令节点立即退出而非等待 6s 全局超时。
        """
        self._ack_timer.stop()
        self._global_timer.stop()
        self._pending_ack_cmd = None
        self._emit_log("error", msg)
        # 尝试发 CANCEL 释放节点状态（force=True 即使断连也尝试）
        # 仅在仍连接时尝试，避免无意义的发送日志
        if self._ctx.is_connected():
            try:
                cancel_payload = build_cancel_payload()
                self._send_frame(cancel_payload, fd=False, force=True)
                self._emit_log("info", _("Boot.Log.CancelOnFail"))
            except Exception as e:
                logger.warning("失败后发送 CANCEL 异常: %s", e)
        self._set_state(BootState.FAILED)
        self.finished.emit(False, msg)

    def _fail_block(self, msg: str) -> None:
        """块级失败。"""
        self._fail(_("Boot.Log.BlockFailed").format(self._expected_block, msg))

    # ------------------------------------------------------------------ #
    #  辅助
    # ------------------------------------------------------------------ #
    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed.emit(state)

    def _emit_log(self, level: str, msg: str) -> None:
        self.log.emit(level, msg)


def build_cancel_payload() -> bytes:
    return P.build_cancel()


def _err_name(code: int) -> str:
    try:
        return P.Err(code).name
    except ValueError:
        return f"UNKNOWN({code:#04X})"
