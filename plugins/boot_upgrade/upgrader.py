"""Bootloader 升级状态机 — 在宿主 CAN worker 线程上运行。

UpgradeSignals: QObject, 驻留主线程, 发射信号更新 UI。
UpgradeTask: plain object, worker 线程调用 task.run(bus)。

对齐 flash_tool/worker.py 的稳定实现：
- 同步 while 循环状态机
- 可配置帧间隔和中途 NACK 拦截
- _last_rx_monotonic 节点失联检测
- 断点续传 + 重同步 (RESYNC_STATUS)
"""
from __future__ import annotations

import logging
from queue import Empty, SimpleQueue
from threading import Event, Thread
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from canable_sdk import ZDTCanable, CANFrame
from . import protocol as P
from .protocol import Cmd, Err, parse_nack_block_index, RESYNC_STATUS

logger = logging.getLogger("plugin.boot_upgrade")

# ── 超时 / 重试常量 (对齐 flash_tool) ──
BLOCK_ACK_TIMEOUT = 1.0
HANDSHAKE_TIMEOUT = 5.0
MAX_RETRIES = 3
NODE_LOST_TIMEOUT = 6.0
MAX_SAME_BLOCK = 5
DEFAULT_FRAME_INTERVAL_MS = 1
MAX_FRAME_INTERVAL_MS = 50


class BootConfig:
    """升级配置 (由 UI 构建)。"""
    def __init__(self, *, fw: bytes, fw_version: int = 0x0100,
                 hw_id: int = 0x0001, max_frame_size: int = 64,
                 host_id: int = P.DEFAULT_HOST_ID,
                 frame_interval_ms: int = DEFAULT_FRAME_INTERVAL_MS):
        if not 0 <= frame_interval_ms <= MAX_FRAME_INTERVAL_MS:
            raise ValueError(f"frame_interval_ms must be in 0..{MAX_FRAME_INTERVAL_MS}")
        self.fw = fw
        self.fw_version = fw_version & 0xFFFF
        self.hw_id = hw_id & 0xFFFF
        self.max_frame_size = max_frame_size
        self.host_id = host_id & 0x7FF
        self.node_id = (host_id + 1) & 0x7FF
        self.frame_interval_ms = frame_interval_ms


class UpgradeSignals(QObject):
    """升级过程信号 (主线程 QObject，供 widget 连接)。"""
    state_changed = Signal(str)
    progress = Signal(int, int)
    block_progress = Signal(int, int)
    log = Signal(str, str)
    timing = Signal(float, float, int)
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
        self._responses = SimpleQueue()
        self._stop_rx = Event()
        self._next_send_at = 0.0
        self._previous_data_send = None
        self._gap_count = 0
        self._gap_total = 0.0
        self._gap_min = float("inf")

    def cancel(self):
        """主线程调用：请求取消升级。"""
        self.cancel_requested = True

    # ── 由 worker 线程调用 ──
    def run(self, bus: ZDTCanable):
        """在 worker 线程上执行同步升级状态机。bus 是宿主已打开的 ZDTCanable。"""
        self._bus = bus
        success = False
        message = "升级完成"
        receiver = Thread(target=self._receive_responses, name="boot-upgrade-rx")
        try:
            receiver.start()
            self._do_upgrade()
            success = True
        except Exception as e:
            self._log_e(f"升级失败: {e}")
            message = str(e)
        finally:
            if not success and self.cancel_requested:
                try:
                    self._send(P.build_cancel(), 8)
                    self._log_i("→ CANCEL (节点退回 IDLE)")
                except Exception:
                    pass
            self._stop_rx.set()
            if receiver.ident is not None:
                receiver.join()
            if self._gap_count:
                average_ms = 1000 * self._gap_total / self._gap_count
                min_ms = 1000 * self._gap_min
                logger.info("Host DATA TX spacing: set %d ms, avg %.2f ms, min %.2f ms (%d samples)",
                            self._cfg.frame_interval_ms, average_ms, min_ms, self._gap_count)
                self._sig.timing.emit(average_ms, min_ms, self._gap_count)
            self._sig.finished.emit(success, message)

    # ── 日志 ──
    def _log_i(self, msg: str):
        self._sig.log.emit("info", msg)

    def _log_w(self, msg: str):
        self._sig.log.emit("warn", msg)

    def _log_e(self, msg: str):
        self._sig.log.emit("error", msg)

    # ── CAN 收发 ──
    def _wait_send_slot(self):
        # Python 3.12 on Windows uses GetTickCount64 for monotonic().
        remaining = self._next_send_at - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

    def _send(self, data: bytes, frame_size: int):
        self._wait_send_slot()
        if self.cancel_requested and data[0] != Cmd.CANCEL:
            raise RuntimeError("用户取消")
        frame = CANFrame(
            can_id=self._cfg.host_id, data=data.ljust(frame_size, b'\x00'),
            extended=False, fd=frame_size > 8, brs=False,
        )
        sent_at = time.perf_counter()
        self._bus.send(frame)
        self._next_send_at = sent_at + self._cfg.frame_interval_ms / 1000
        cmd = data[0]
        if cmd in (Cmd.DATA, Cmd.DATA_END) and self._previous_data_send is not None:
            gap = sent_at - self._previous_data_send
            self._gap_count += 1
            self._gap_total += gap
            self._gap_min = min(self._gap_min, gap)
        self._previous_data_send = sent_at if cmd == Cmd.DATA else None

    def _receive_responses(self):
        """Keep USB reads off the frame pacing path while the worker owns the bus."""
        try:
            while not self._stop_rx.is_set():
                frame = self._bus.receive(timeout=0.05)
                if (frame is not None and frame.can_id == self._cfg.node_id
                        and not frame.extended and not frame.is_tx and not frame.is_error
                        and len(frame.data) >= 2 and frame.data[0] in (Cmd.ACK, Cmd.NACK)):
                    self._responses.put(frame)
        except Exception as exc:
            self._responses.put(exc)

    def _take_response(self, timeout: float = 0.0) -> Optional[CANFrame]:
        try:
            response = self._responses.get(timeout=timeout)
        except Empty:
            return None
        if isinstance(response, Exception):
            raise response
        self._last_rx_monotonic = time.perf_counter()
        return response

    def _recv(self, timeout: float) -> Optional[CANFrame]:
        end_time = time.perf_counter() + timeout
        while time.perf_counter() < end_time:
            if self.cancel_requested:
                raise RuntimeError("用户取消")
            remaining = end_time - time.perf_counter()
            if remaining <= 0:
                break
            frame = self._take_response(min(remaining, 0.05))
            if frame is not None:
                return frame
        return None

    def _poll_response(self) -> Optional[CANFrame]:
        """取出发帧间隔内已经收到的响应。"""
        return self._take_response()

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
            if expected_cmd == Cmd.DATA_END and acked_cmd == Cmd.DATA and self._reseek_index(data) is not None:
                return False, resp
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
                     f"HW 0x{cfg.hw_id:04X}, frame={cfg.max_frame_size}, "
                     f"interval={cfg.frame_interval_ms}ms")
        self._log_i("=" * 50)

        blocks = _block_chunks(fw_data)
        total_blocks = len(blocks)

        self._last_rx_monotonic = time.perf_counter()

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
                    if time.perf_counter() - self._last_rx_monotonic > NODE_LOST_TIMEOUT:
                        raise TimeoutError(f"节点失联超过 {NODE_LOST_TIMEOUT:.0f}s")
                    self._log_w(f"Block {block_idx} DATA_START 无响应, 重试…")
                    continue
                n_code = resp.data[2] if len(resp.data) > 2 else 0
                raise RuntimeError(f"Block {block_idx} DATA_START NACK: {_err_name(n_code)} (0x{n_code:02X})")

            tag = f"{block_idx + 1}/{total_blocks}"
            if attempt > 0:
                self._log_i(f"{tag} 重试 #{attempt}")
            self._log_i(f"{tag} DATA_START → ACK ✓")

            # DATA 帧序列。在下一帧的发送时刻先检查已到达的 NACK。
            interrupted_to = None
            total_frames = frames_per_block
            checksum = P.calc_16bit_checksum(block)
            for seq_idx in range(total_frames):
                self._wait_send_slot()
                poll = self._poll_response()
                reseek = self._reseek_index(poll.data) if poll is not None else None
                if reseek is not None:
                    code = poll.data[2] if len(poll.data) > 2 else 0
                    self._log_w(f"途中拦截 NACK [{_err_name(code)}]: 重同步到块 {reseek}")
                    interrupted_to = reseek
                    break
                chunk = block[seq_idx * d:(seq_idx + 1) * d]
                data = (P.build_data_end(seq_idx, checksum, chunk) if seq_idx == total_frames - 1
                        else P.build_data(seq_idx, chunk))
                self._send(data, cfg.max_frame_size)
                self._sig.block_progress.emit(seq_idx + 1, total_frames)

            if interrupted_to is not None:
                same_block_streak = (same_block_streak + 1) if interrupted_to == block_idx else 0
                block_idx = interrupted_to
                attempt = 0
                continue

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
            if time.perf_counter() - self._last_rx_monotonic > NODE_LOST_TIMEOUT:
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
