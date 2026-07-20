"""Bootloader 升级状态机 — 在宿主 CAN worker 线程上运行。

UpgradeSignals: QObject, 驻留主线程, 发射信号更新 UI。
UpgradeTask: plain object, worker 线程调用 task.run(bus)。

对齐 flash_tool/worker.py 的稳定实现：
- 同步 while 循环状态机
- _poll_response() 帧间 1ms 节流 + 中途 NACK 拦截
- _last_rx_monotonic 节点失联检测
- 断点续传 + 重同步 (RESYNC_STATUS)
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from canable_sdk import ZDTCanable, CANFrame
from . import protocol as P
from .protocol import Cmd, Err, parse_nack_block_index, RESYNC_STATUS

# ── 超时 / 重试常量 (对齐 flash_tool) ──
BLOCK_ACK_TIMEOUT = 1.0
HANDSHAKE_TIMEOUT = 5.0
MAX_RETRIES = 3
NODE_LOST_TIMEOUT = 6.0
MAX_SAME_BLOCK = 5


class BootConfig:
    """升级配置 (由 UI 构建)。"""
    def __init__(self, *, fw: bytes, fw_version: int = 0x0100,
                 hw_id: int = 0x0001, max_frame_size: int = 64,
                 host_id: int = 0x701):
        self.fw = fw
        self.fw_version = fw_version & 0xFFFF
        self.hw_id = hw_id & 0xFFFF
        self.max_frame_size = max_frame_size
        self.host_id = host_id & 0x7FF
        self.node_id = (host_id + 1) & 0x7FF


class UpgradeSignals(QObject):
    """升级过程信号 (主线程 QObject，供 widget 连接)。"""
    state_changed = Signal(str)
    progress = Signal(int, int)
    block_progress = Signal(int, int)
    log = Signal(str, str)
    finished = Signal(bool, str)


class UpgradeTask:
    """升级状态机 — plain object，在 worker 线程上执行。

    用法::

        signals = UpgradeSignals()
        signals.state_changed.connect(...)
        task = UpgradeTask(config, signals)
        ctx.start_upgrade(task)  # worker 线程调用 task.run(bus)
    """

    def __init__(self, config: BootConfig, signals: UpgradeSignals):
        self._cfg = config
        self._sig = signals
        self.cancel_requested = False

    def cancel(self):
        """主线程调用：请求取消升级。"""
        self.cancel_requested = True

    # ── 由 worker 线程调用 ──
    def run(self, bus: ZDTCanable):
        """在 worker 线程上执行同步升级状态机。bus 是宿主已打开的 ZDTCanable。"""
        self._bus = bus
        success = False
        try:
            self._do_upgrade()
            success = True
            self._sig.finished.emit(True, "升级完成")
        except Exception as e:
            self._log_e(f"升级失败: {e}")
            self._sig.finished.emit(False, str(e))
        finally:
            if not success and self.cancel_requested:
                try:
                    self._send(P.build_cancel(), 8)
                    self._log_i("→ CANCEL (节点退回 IDLE)")
                except Exception:
                    pass

    # ── 日志 ──
    def _log_i(self, msg: str):
        self._sig.log.emit("info", msg)

    def _log_w(self, msg: str):
        self._sig.log.emit("warn", msg)

    def _log_e(self, msg: str):
        self._sig.log.emit("error", msg)

    # ── CAN 收发 ──
    def _send(self, data: bytes, frame_size: int):
        frame = CANFrame(
            can_id=self._cfg.host_id, data=data.ljust(frame_size, b'\x00'),
            extended=False, fd=frame_size > 8, brs=False,
        )
        self._bus.send(frame)

    def _recv(self, timeout: float) -> Optional[CANFrame]:
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            if self.cancel_requested:
                raise RuntimeError("用户取消")
            remaining = end_time - time.monotonic()
            if remaining <= 0:
                break
            frame = self._bus.receive(timeout=min(remaining, 0.2))
            if frame is not None and frame.can_id == self._cfg.node_id:
                self._last_rx_monotonic = time.monotonic()
                return frame
        return None

    def _poll_response(self) -> Optional[CANFrame]:
        """1ms 短超时：帧间节流 + 中途 NACK 拦截。"""
        frame = self._bus.receive(timeout=0.001)
        if frame is not None and frame.can_id == self._cfg.node_id:
            self._last_rx_monotonic = time.monotonic()
            return frame
        return None

    def _reseek_index(self, data: Optional[bytes]) -> Optional[int]:
        if data is None or len(data) < 3 or data[0] != Cmd.NACK:
            return None
        code = data[2] if len(data) > 2 else 0
        if code in RESYNC_STATUS:
            return parse_nack_block_index(data)
        return None

    # ── 等待响应 ──
    def _wait_ack(self, expected_cmd: int, timeout: float = HANDSHAKE_TIMEOUT) -> None:
        while True:
            resp = self._recv(timeout)
            if resp is None:
                raise TimeoutError(f"等待 ACK(0x{expected_cmd:02X}) 超时 ({timeout}s)")
            data = resp.data
            if len(data) < 2:
                continue
            cmd = data[0]
            if cmd == Cmd.NACK:
                continue
            if cmd != Cmd.ACK:
                continue
            if data[1] != expected_cmd:
                continue
            return

    def _wait_block(self, expected_cmd: int) -> tuple:
        while True:
            resp = self._recv(BLOCK_ACK_TIMEOUT)
            if resp is None:
                return False, None
            data = resp.data
            if len(data) < 2:
                continue
            cmd, acked_cmd = data[0], data[1]
            if cmd == Cmd.ACK and acked_cmd == expected_cmd:
                return True, resp
            if cmd == Cmd.NACK and acked_cmd == expected_cmd:
                return False, resp

    # ── 主状态机 ──
    def _do_upgrade(self):
        cfg = self._cfg
        fw_data = cfg.fw
        actual_fw_size = len(fw_data)
        fw_checksum = P.calc_32bit_checksum(fw_data)

        self._log_i("=" * 50)
        self._log_i(f"固件升级: {actual_fw_size}B, v0x{cfg.fw_version:04X}, "
                     f"HW 0x{cfg.hw_id:04X}, frame={cfg.max_frame_size}")
        self._log_i("=" * 50)

        blocks = _block_chunks(fw_data)
        total_blocks = len(blocks)

        self._last_rx_monotonic = time.monotonic()

        # Phase 1: Handshake
        self._sig.state_changed.emit("handshake")
        self._log_i("握手: START")
        self._send(P.build_start(actual_fw_size, cfg.hw_id, cfg.max_frame_size), 8)
        self._wait_ack(Cmd.START)
        self._log_i("握手: START → ACK ✓")

        self._send(P.build_metadata(fw_checksum, cfg.fw_version), cfg.max_frame_size)
        self._wait_ack(Cmd.METADATA)
        self._log_i("握手: METADATA → ACK ✓")

        # Phase 2: Data Transfer
        self._sig.state_changed.emit("transfer")
        d = cfg.max_frame_size - 2
        frames_per_block = (P.BLOCK_SIZE + d - 1) // d

        block_idx = 0
        attempt = 0
        same_block_streak = 0
        while block_idx < total_blocks:
            if self.cancel_requested:
                raise RuntimeError("用户取消")
            block = blocks[block_idx]
            self._sig.progress.emit(block_idx, total_blocks)

            # DATA_START
            self._send(P.build_data_start(block_idx), 8)
            if self.cancel_requested:
                raise RuntimeError("用户取消")
            ack, resp = self._wait_block(Cmd.DATA_START)
            if not ack:
                reseek = self._reseek_index(resp.data) if resp is not None else None
                if reseek is not None:
                    self._log_w(f"重同步: 期望块 {reseek}, 跳转")
                    same_block_streak = (same_block_streak + 1) if reseek == block_idx else 0
                    block_idx = reseek
                    attempt = 0
                    continue
                if resp is None:
                    if time.monotonic() - self._last_rx_monotonic > NODE_LOST_TIMEOUT:
                        raise TimeoutError(f"节点失联超过 {NODE_LOST_TIMEOUT:.0f}s")
                    self._log_w(f"Block {block_idx} DATA_START 无响应, 重试…")
                    continue
                n_code = resp.data[2] if len(resp.data) > 2 else 0
                raise RuntimeError(f"Block {block_idx} DATA_START NACK: {_err_name(n_code)} (0x{n_code:02X})")

            tag = f"{block_idx + 1}/{total_blocks}"
            if attempt > 0:
                self._log_i(f"{tag} 重试 #{attempt}")
            self._log_i(f"{tag} DATA_START → ACK ✓")

            # DATA 帧序列 (帧间 1ms 节流 + NACK 拦截)
            interrupted_to = None
            total_frames = frames_per_block
            for seq_idx in range(frames_per_block - 1):
                chunk = block[seq_idx * d:(seq_idx + 1) * d]
                self._send(P.build_data(seq_idx, chunk), cfg.max_frame_size)
                self._sig.block_progress.emit(seq_idx + 1, total_frames)
                poll = self._poll_response()
                reseek = self._reseek_index(poll.data) if poll is not None else None
                if reseek is not None:
                    code = poll.data[2] if len(poll.data) > 2 else 0
                    self._log_w(f"途中拦截 NACK [{_err_name(code)}]: 重同步到块 {reseek}")
                    interrupted_to = reseek
                    break
                if self.cancel_requested:
                    raise RuntimeError("用户取消")

            if interrupted_to is not None:
                same_block_streak = (same_block_streak + 1) if interrupted_to == block_idx else 0
                block_idx = interrupted_to
                attempt = 0
                continue

            # DATA_END
            last_start = (frames_per_block - 1) * d
            remaining = block[last_start:last_start + d]
            checksum = P.calc_16bit_checksum(block)
            end_raw = P.build_data_end(frames_per_block - 1, checksum, remaining)
            self._send(end_raw, cfg.max_frame_size)
            self._sig.block_progress.emit(total_frames, total_frames)
            if self.cancel_requested:
                raise RuntimeError("用户取消")

            ack, resp = self._wait_block(Cmd.DATA_END)
            if ack:
                self._log_i(f"{tag} DATA_END → ACK ✓")
                block_idx += 1
                attempt = 0
                same_block_streak = 0
                continue

            reseek = self._reseek_index(resp.data) if resp is not None else None
            if reseek is not None:
                self._log_w(f"重同步: 期望块 {reseek}, 跳转")
                if reseek == block_idx:
                    same_block_streak += 1
                    if same_block_streak > MAX_SAME_BLOCK:
                        self._log_w(f"同块 {block_idx} 重试 {same_block_streak} 次, 跳过")
                        block_idx = reseek + 1
                        same_block_streak = 0
                    else:
                        block_idx = reseek
                else:
                    same_block_streak = 0
                    block_idx = reseek
                attempt = 0
                continue
            if resp is not None:
                n_code = resp.data[2] if len(resp.data) > 2 else 0
                if n_code == Err.BLOCK_CHECKSUM:
                    attempt += 1
                    if attempt > MAX_RETRIES:
                        raise RuntimeError(f"Block {block_idx + 1} 校验失败重试超限 ({MAX_RETRIES} 次)")
                    self._log_i(f"{tag} NACK: CHECKSUM, 重试")
                    continue
                raise RuntimeError(f"Block {block_idx + 1} DATA_END NACK: {_err_name(n_code)} (0x{n_code:02X})")
            if time.monotonic() - self._last_rx_monotonic > NODE_LOST_TIMEOUT:
                raise TimeoutError(f"节点失联超过 {NODE_LOST_TIMEOUT:.0f}s")
            self._log_w(f"Block {block_idx + 1} 无响应, 重试…")

        self._sig.progress.emit(total_blocks, total_blocks)
        self._log_i("数据传输完成 ✓")

        # Phase 3: VERIFY + REBOOT
        self._sig.state_changed.emit("verify")
        self._send(P.build_verify(), cfg.max_frame_size)
        self._wait_ack(Cmd.VERIFY)
        self._log_i("校验和通过 ✓")

        self._sig.state_changed.emit("reboot")
        self._send(P.build_reboot(), cfg.max_frame_size)
        resp = self._recv(HANDSHAKE_TIMEOUT)
        if resp is not None and len(resp.data) > 0 and resp.data[0] == Cmd.ACK:
            self._log_i("→ ACK ✓")
        else:
            raise TimeoutError(f"等待 REBOOT ACK 超时 ({HANDSHAKE_TIMEOUT}s)")

        self._sig.state_changed.emit("done")
        self._log_i("=" * 50)
        self._log_i(f"升级完成！({total_blocks} blocks, {actual_fw_size} bytes)")
        self._log_i("=" * 50)


def _block_chunks(fw_data: bytes) -> list[bytes]:
    blocks = []
    for offset in range(0, len(fw_data), P.BLOCK_SIZE):
        block = fw_data[offset:offset + P.BLOCK_SIZE]
        block = block.ljust(P.BLOCK_SIZE, b'\x00')
        blocks.append(block)
    return blocks


def _err_name(code: int) -> str:
    try:
        return Err(code).name
    except ValueError:
        return f"UNKNOWN({code:#04X})"
