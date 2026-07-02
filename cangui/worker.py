"""CAN I/O 工作线程。

把 zdt_canable.ZDTCanable 封装进 QThread，
通过 Qt 信号把帧、状态、错误安全地抛到主线程。
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker, QObject, Slot

from zdt_canable import ZDTCanable, CANFrame

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
    frame_received = Signal(object)        # CANFrame
    state_changed = Signal(bool, str)      # connected, message
    error         = Signal(str)
    bus_stats     = Signal(float, int)     # load%, fps

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

    # ---------- 过滤 ---------- #
    def set_filters(self, filters: List[CANFilter]):
        with QMutexLocker(self._mutex):
            self._filters = list(filters)

    def _pass(self, frame: CANFrame) -> bool:
        """返回 True 表示接收。"""
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

            # 检查 FD 支持
            if self.fd_mode:
                fd_ok = self._bus.check_fd_support()
                if not fd_ok:
                    self.error.emit(
                        "⚠️ 固件可能不支持 CAN FD (Y 命令返回错误)。"
                        "FD 帧发送可能失败，建议切换为经典 CAN 模式。"
                    )
                else:
                    if self.data_bitrate:
                        self._bus.set_data_bitrate(self.data_bitrate)

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
                            f"⚠️ CAN 错误寄存器={err} (非零表示物理层问题："
                            "检查 CANH/CANL 接线、120Ω 终端电阻、GND 共地)")
            except Exception:
                pass
            self.state_changed.emit(True, f"已连接 @ {self.bitrate:,} bps")
        except Exception as e:
            self._bus = None
            self._connected = False
            self.error.emit(f"连接失败: {e}")
            self.state_changed.emit(False, "未连接")

    @Slot()
    def disconnect(self):
        self._running = False
        self._connected = False
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None
        self.state_changed.emit(False, "已断开")

    @Slot(int)
    def set_bitrate_slot(self, bitrate: int):
        was_running = self._running
        if self._bus is not None and self._connected:
            try:
                self._bus.set_bitrate(bitrate)
                self.bitrate = bitrate
                if was_running:
                    self.state_changed.emit(True, f"已连接 @ {bitrate:,} bps")
            except Exception as e:
                self.error.emit(f"设置波特率失败: {e}")
        else:
            self.bitrate = bitrate

    @Slot(object)
    def send(self, frame: CANFrame):
        if self._bus is None or not self._connected:
            self.error.emit("未连接，无法发送")
            return
        # 标记为本机发送，让 trace 面板用绿色区分
        frame.is_tx = True
        frame.timestamp = time.time()
        try:
            self._bus.send(frame)
            logger.info("TX  %s", frame)
            # 同步进 trace 列表（不等回环），让用户立即看到发送成功
            self.frame_received.emit(frame)
            # 记录最近一次发送 FD 帧的时间，用于 bus-off 检测
            if frame.fd:
                self._last_fd_tx_time = time.time()
        except Exception as e:
            self.error.emit(f"发送失败: {e}")
            logger.warning("TX  失败 %s : %s", frame, e)

    # ---------- 主循环 ---------- #
    @Slot()
    def run(self):
        """Qt Concurrent / QThread 入口；也可直接循环调用。"""
        window_s = 1.0
        frame_times: List[float] = []
        self._last_fd_tx_time: float = 0.0
        self._last_rx_time: float = time.time()
        _recovering = False

        while self._running and self._bus is not None:
            try:
                frame = self._bus.receive(timeout=0.05)
            except Exception as e:
                if self._running:
                    self.error.emit(f"接收错误: {e}")
                    logger.warning("RX  失败: %s", e)
                time.sleep(0.1)
                continue

            now = time.time()
            if frame is not None:
                frame.timestamp = now
                frame_times.append(now)
                frame_times = [t for t in frame_times if now - t <= window_s]
                self._last_rx_time = now
                _recovering = False
                logger.info("RX  %s", frame)
                if self._pass(frame):
                    self.frame_received.emit(frame)

            # Bus-off 检测：发送 FD 帧后超过 3 秒未收到任何数据，尝试恢复
            if (self._last_fd_tx_time > 0
                    and now - self._last_fd_tx_time > 3.0
                    and now - self._last_rx_time > 3.0
                    and not _recovering):
                logger.warning("疑似 bus-off（FD 发送后 %0.1fs 无接收），尝试恢复",
                               now - self._last_fd_tx_time)
                try:
                    self._bus.recover()
                    self._last_rx_time = time.time()
                    self._last_fd_tx_time = 0.0
                    _recovering = True
                    self.error.emit("CAN 控制器疑似 bus-off，已自动恢复。"
                                    "FD 帧可能未被总线 ACK。")
                except Exception as e:
                    logger.warning("恢复失败: %s", e)

            # 统计：fps + 总线负载（按 8 字节 ≈ 128 bit 计算）
            fps = len(frame_times)
            load = min(100.0, fps * 128.0 * 100.0 / self.bitrate) if self.bitrate else 0.0
            self.bus_stats.emit(load, fps)


