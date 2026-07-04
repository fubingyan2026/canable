"""CAN I/O 工作线程。

把 canable_sdk.ZDTCanable 封装进 QThread，
通过 Qt 信号把帧、状态、错误安全地抛到主线程。
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

import usb.core
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker, QObject, Slot

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
        self._last_error_notify = 0.0    # 上次错误帧通知时间
        self._error_count = 0            # 连续错误帧计数
        self._last_error_time = 0.0     # 上次错误帧时间

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
                        "⚠️ 固件不支持 CAN FD，已回退到经典 CAN 模式。"
                        "请取消勾选 CAN FD 选项。"
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
        if not self._bus.running:
            self.error.emit("控制器未启动，无法发送")
            return
        # 标记为本机发送，让 trace 面板用绿色区分
        frame.is_tx = True
        frame.timestamp = time.time()
        try:
            self._bus.send(frame)
            logger.info("TX  %s", frame)
            # 同步进 trace 列表（不等回环），让用户立即看到发送成功
            self.frame_received.emit(frame)
        except usb.core.USBError as e:
            # Pipe error: canable_sdk 已在 send() 内部完成 recover + TX 节流
            # 此处仅通知 UI, 不重复恢复
            logger.warning("TX  USB 错误 (已自动恢复): %s", e)
            self.error.emit("发送失败: 控制器已自动恢复，请重试")
        except Exception as e:
            self.error.emit(f"发送失败: {e}")
            logger.warning("TX  失败 %s : %s", frame, e)

    # ---------- 主循环 ---------- #
    @Slot()
    def run(self):
        """Qt Concurrent / QThread 入口；也可直接循环调用。"""
        window_s = 1.0
        frame_times: List[float] = []

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
                # 错误帧处理
                if frame.is_error:
                    is_busoff = "BUS-OFF" in frame._error_info
                    is_noack  = "NO-ACK" in frame._error_info

                    if is_busoff:
                        # BUS-OFF: 真正严重错误, 需要恢复控制器
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
                                self.error.emit("BUS-OFF, 已自动恢复控制器")
                            except Exception as e:
                                logger.warning("自动恢复失败: %s", e)
                            self._error_count = 0
                            time.sleep(0.2)
                    elif is_noack:
                        # NO-ACK: 固件 LEC 寄存器粘滞, 会持续发送错误帧
                        # 根因: 总线上无设备应答本机发送的帧 (正常现象)
                        # recover() 无法解决 NO-ACK, 仅首次通知, 之后静默
                        if now - self._last_error_notify >= 5.0:
                            logger.info("CAN NO-ACK (LEC 粘滞, 可能无设备应答)")
                            self._last_error_notify = now
                        # 不计数, 不触发 recover()
                    else:
                        # 非严重错误 (CTRL-ERR 等): 仅日志，不通知 UI
                        logger.debug("CAN 状态: %s", frame._error_info)
                    continue

                # TX 回环帧: 固件回传的发送确认，已在 send() 中直接显示，跳过
                if frame.is_tx:
                    continue

                frame.timestamp = now
                frame_times.append(now)
                frame_times = [t for t in frame_times if now - t <= window_s]
                logger.info("RX  %s", frame)
                if self._pass(frame):
                    self.frame_received.emit(frame)

            # 统计：fps + 总线负载
            # 经典 CAN: ~128 bit/帧 (含仲裁+控制+数据+CRC+ACK+EOF)
            # CAN FD: 仲裁相 ~128 bit + 数据相 (data_len * 10 bit)
            #   - 无 BRS: 全程按标称波特率
            #   - 有 BRS: 数据相按 data_bitrate，需折算
            fps = len(frame_times)
            if frame is not None and fps > 0:
                if frame.fd:
                    arb_bits = 128
                    data_bits = len(frame.data) * 10
                    if frame.brs and self.data_bitrate and self.data_bitrate > 0:
                        # BRS: 数据相用更高波特率，折算到标称波特率
                        effective_bits = arb_bits + data_bits * (self.bitrate / self.data_bitrate)
                    else:
                        effective_bits = arb_bits + data_bits
                else:
                    effective_bits = 128
                load = min(100.0, fps * effective_bits * 100.0 / self.bitrate) if self.bitrate else 0.0
            else:
                load = 0.0
            self.bus_stats.emit(load, fps)


