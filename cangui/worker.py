"""CAN I/O 工作线程。

把 canable_sdk.ZDTCanable 封装进 QThread，
通过 Qt 信号把帧、状态、错误安全地抛到主线程。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import List, Optional

import usb.core
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker, QObject, Slot

from .i18n import _

from canable_sdk import ZDTCanable, CANFrame

logger = logging.getLogger("cangui.worker")


# --------------------------------------------------------------------------- #
#  过滤规则
# --------------------------------------------------------------------------- #
class CANFilter:
    """ID 区间过滤。pass_discard=True 表示丢弃区间内，否则仅放行区间内。"""
    def __init__(self,
                 can_id_min: int = 0,
                 can_id_max: int = 0x7FF,
                 extended: bool = False,
                 pass_discard: bool = True):
        self.can_id_min = can_id_min
        self.can_id_max = can_id_max
        self.extended   = extended
        self.pass_discard = pass_discard  # True=丢弃, False=放行

    def matches(self, frame: CANFrame) -> bool:
        if self.extended != frame.extended:
            return False
        return self.can_id_min <= frame.can_id <= self.can_id_max


# --------------------------------------------------------------------------- #
#  Worker
# --------------------------------------------------------------------------- #
class CANWorker(QObject):
    """运行在子线程内的 CAN 控制器。"""

    # ---- 信号 ---- #
    state_changed = Signal(bool, str)      # connected, message
    error         = Signal(str)
    bus_stats     = Signal(float, int)     # load%, fps
    noack_warning = Signal(str)            # NO-ACK 提示

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._bus: Optional[ZDTCanable] = None
        self._connected = False
        self._running   = False
        self._mutex     = QMutex()
        self._filters: List[CANFilter] = []
        self.bitrate = 500_000
        self.fd_mode = False
        self.data_bitrate: Optional[int] = None
        self._last_error_notify = 0.0    # 上次错误帧通知时间
        self._error_count = 0            # 连续错误帧计数
        self._last_error_time = 0.0      # 上次错误帧时间
        self._frame_buffer = deque(maxlen=10000)
        self._buffer_mutex = QMutex()
        # 发送队列：主线程放入，子线程在 run() 中取出执行
        self._send_queue: deque = deque()
        self._send_mutex = QMutex()

    # ---------- 过滤 ---------- #
    def set_filters(self, filters: List[CANFilter]):
        with QMutexLocker(self._mutex):
            self._filters = list(filters)

    def _pass(self, frame: CANFrame) -> bool:
        """返回 True 表示接收。错误帧始终放行。"""
        if frame.is_error:
            return True
        with QMutexLocker(self._mutex):
            filters = self._filters
        if not filters:
            return True
        for f in filters:
            if f.matches(frame):
                # 命中规则：依据 pass_discard 决定
                return not f.pass_discard
        # 未命中任何规则 -> 默认放行
        return True

    # ---------- 生命周期 ---------- #
    @Slot()
    def connect(self):
        if self._connected:
            return
        try:
            self._bus = ZDTCanable()
            self._bus.open()
            self._bus.set_bitrate(self.bitrate)

            # 查询固件版本
            ver = self._bus.get_version()
            if ver:
                logger.info("固件版本: %s", ver)

            # FD 模式设置
            if self.fd_mode:
                fd_ok = self._bus.check_fd_support()
                if not fd_ok:
                    self.error.emit(
                        f"⚠️ {_('Error.FDNotSupported')}"
                    )
                    # 固件不支持 FD，不启用 FD 模式
                    self.fd_mode = False
                else:
                    if self.data_bitrate:
                        self._bus.set_data_bitrate(self.data_bitrate)
                    # 仅在固件支持 FD 时才设置标志
                    self._bus.fd_mode = True

            self._bus.start()
            self._connected = True
            self._running   = True
            # 诊断：读取错误寄存器，帮助用户判断物理层是否正常
            try:
                err = self._bus.read_error_register()
                if err is not None:
                    logger.info("CAN 错误寄存器: %s (0=正常, 非0=物理层问题)", err)
                    if str(err) != "0":
                        self.error.emit(
                            f"⚠️ {_('Error.CANErrorReg')}={err} ({_('Error.CANErrorRegHint')})"
                        )
            except Exception:
                pass
            self.state_changed.emit(True, f"{_('Status.ConnectedAt')} {self.bitrate:,} bps")
        except Exception as e:
            self._bus = None
            self._connected = False
            self.error.emit(f"{_('Error.ConnectFailed')}: {e}")
            self.state_changed.emit(False, _("Status.Disconnected"))

    @Slot()
    def disconnect(self):
        self._running = False
        self._connected = False

    def take_batch(self):
        with QMutexLocker(self._buffer_mutex):
            batch = list(self._frame_buffer)
            self._frame_buffer.clear()
        return batch

    @Slot(int)
    def set_bitrate_slot(self, bitrate: int):
        was_running = self._running
        if self._bus is not None and self._connected:
            try:
                self._bus.set_bitrate(bitrate)
                self.bitrate = bitrate
                if was_running:
                    self.state_changed.emit(True, f"{_('Status.ConnectedAt')} {bitrate:,} bps")
            except Exception as e:
                self.error.emit(f"{_('Error.BitrateFailed')}: {e}")
        else:
            self.bitrate = bitrate

    def _calc_bus_load(self, now: float, frame: CANFrame, fps: int) -> float:
        if fps == 0 or not self.bitrate:
            return 0.0
        # 按帧实际位长度估算（含 SOF/控制/CRC/ACK/EOF/IFS 的固定开销）
        # Classic CAN: ~47 固定 + 8*N_data + stuff bits (~19%)
        # CAN FD:     ~67 固定 + 8*N_data + stuff bits
        data_len = len(frame.data)
        if frame.fd:
            fixed_bits = 67
            data_bits = data_len * 8
            if frame.brs and self.data_bitrate and self.data_bitrate > 0:
                # 数据相用数据波特率传输
                effective_bits = fixed_bits + data_bits * (self.bitrate / self.data_bitrate)
            else:
                effective_bits = fixed_bits + data_bits
        else:
            # Classic: 固定开销 ~47 bits (SOF+Arbitration+Control+CRC+ACK+EOF+IFS)
            effective_bits = 47 + data_len * 8
        # 粗略加上 stuff bits (约 19% 冗余)
        effective_bits *= 1.19
        return min(100.0, fps * effective_bits * 100.0 / self.bitrate)

    @Slot(object)
    def send(self, frame: CANFrame):
        """主线程调用：将帧放入发送队列，由 run() 循环在子线程实际发送。

        这样避免了跨线程直接访问 _bus（与 receive() 循环竞争）。
        """
        if not self._connected:
            self.error.emit(_("Error.NotConnected"))
            return
        with QMutexLocker(self._send_mutex):
            self._send_queue.append(frame)

    def _process_send_queue(self):
        """在 run() 循环中调用，从队列取出帧并实际发送（子线程上下文）。"""
        if not self._send_queue:
            return
        # 批量取出，减少锁竞争
        with QMutexLocker(self._send_mutex):
            pending = list(self._send_queue)
            self._send_queue.clear()
        for frame in pending:
            if not self._running or self._bus is None:
                break
            frame.is_tx = True
            frame.timestamp = time.time()
            try:
                self._bus.send(frame)
                logger.debug("TX  %s", frame)
                with QMutexLocker(self._buffer_mutex):
                    self._frame_buffer.append(frame)
            except Exception as e:
                if isinstance(e, usb.core.USBError):
                    logger.warning("TX  USB 错误 (已自动恢复): %s", e)
                    self.error.emit(_("Error.SendFailedRecover"))
                else:
                    self.error.emit(f"{_('Error.SendFailed')}: {e}")
                    logger.warning("TX  失败 %s : %s", frame, e)

    # ---------- 主循环 ---------- #
    @Slot()
    def run(self):
        window_s = 1.0
        frame_times: deque = deque(maxlen=2000)
        last_stats_emit = 0.0

        while self._running and self._bus is not None:
            # 处理主线程投递的发送请求
            self._process_send_queue()

            try:
                frame = self._bus.receive(timeout=0.01)
            except Exception as e:
                if self._running:
                    self.error.emit(f"{_('Error.ReceiveError')}: {e}")
                    logger.warning("RX  失败: %s", e)
                time.sleep(0.1)
                continue

            now = time.time()
            if frame is not None:
                if frame.is_error:
                    is_busoff = "BUS-OFF" in frame._error_info
                    is_noack  = "NO-ACK" in frame._error_info

                    if is_busoff:
                        if now - self._last_error_time > 1.0:
                            self._error_count = 1
                        else:
                            self._error_count += 1
                        self._last_error_time = now

                        if now - self._last_error_notify >= 2.0:
                            logger.warning("CAN 严重错误: %s (连续 %d 次)",
                                           frame._error_info, self._error_count)
                            self.error.emit(f"CAN: {frame._error_info}")
                            self._last_error_notify = now

                        if self._error_count >= 10:
                            logger.warning("BUS-OFF 持续, 自动恢复控制器")
                            try:
                                self._bus.recover()
                                self.error.emit(f"{_('Error.BusOffRecover')}")
                            except Exception as e:
                                logger.warning("自动恢复失败: %s", e)
                            self._error_count = 0
                            time.sleep(0.2)
                    elif is_noack:
                        if now - self._last_error_notify >= 5.0:
                            self.noack_warning.emit("NO-ACK")
                            logger.info("CAN NO-ACK (LEC 粘滞, 可能无设备应答)")
                            self._last_error_notify = now
                    else:
                        logger.debug("CAN 状态: %s", frame._error_info)
                    continue

                if frame.is_tx:
                    frame_times.append(now)
                    while frame_times and frame_times[0] < now - window_s:
                        frame_times.popleft()
                    continue

                frame.timestamp = now
                frame_times.append(now)
                while frame_times and frame_times[0] < now - window_s:
                    frame_times.popleft()
                logger.debug("RX  %s", frame)
                if self._pass(frame):
                    with QMutexLocker(self._buffer_mutex):
                        self._frame_buffer.append(frame)

            fps = len(frame_times)
            load = 0.0
            if frame is not None and fps > 0:
                load = self._calc_bus_load(now, frame, fps)

            # 仅在帧到来或负载非零时 emit，空闲时不打扰 UI
            if frame is not None or load > 0.0 or last_stats_emit == 0.0:
                if now - last_stats_emit >= 0.1:
                    self.bus_stats.emit(load, fps)
                    last_stats_emit = now

        # cleanup: close bus from correct thread
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None
        self.state_changed.emit(False, _("Status.Disconnected"))


