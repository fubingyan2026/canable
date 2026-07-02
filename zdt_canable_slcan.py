#!/usr/bin/env python3
"""ZDT_CANable_2.0pro slcan 后端（CDC ACM 模式）

slcan 协议摘要：
  O\\r   打开 CAN       C\\r   关闭 CAN
  S<n>\\r 设置位速率    E\\r   查错误寄存器
  M0/M1\\r Normal/Silent 模式
  Y2/Y5\\r 设置 CAN FD 数据相波特率 (2M/5M)
  t/T/r/R 经典帧（标准/扩展/远程标准/远程扩展）
  d/D/b/B CAN FD 帧（标准/扩展, 无BRS/有BRS）
"""

import glob
import os
import threading
import time
import logging
from typing import List, Optional

try:
    import serial
except ImportError:
    serial = None

from zdt_canable import CANFrame

logger = logging.getLogger("zdt_canable.slcan")

# 标准 slcan 波特率码（与 canable2 固件一致）
SLCAN_BITRATE_CODES = {
    10_000:    "0",
    20_000:    "1",
    50_000:    "2",
    100_000:   "3",
    125_000:   "4",
    250_000:   "5",
    500_000:   "6",
    750_000:   "7",
    1_000_000: "8",
    83_300:    "9",
}

# CAN FD 数据相波特率码（canable2 固件 Y 命令）
SLCAN_DATA_BITRATE_CODES = {
    2_000_000: "Y2",
    5_000_000: "Y5",
}

# 参考 python-can：串口打开后等待设备就绪的时间
_SLEEP_AFTER_SERIAL_OPEN = 2.0

LINE_TERMINATOR = b"\r"


# ----------------------------------------------------------------------------
#  设备发现
# ----------------------------------------------------------------------------
def list_serial_devices() -> List[dict]:
    """列出系统中所有疑似 CANable 设备的串口。"""
    devs = []
    for path in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        name = os.path.basename(path)
        try:
            dev_link = os.readlink(f"/sys/class/tty/{name}/device")
        except OSError:
            continue
        parts = dev_link.rstrip("/").split("/")
        usb_bus = None
        for p in parts:
            if "-" in p and p[0].isdigit():
                usb_bus = p.split(":")[0]
                break
        if not usb_bus:
            continue
        vid = pid = None
        try:
            with open(f"/sys/bus/usb/devices/{usb_bus}/idVendor") as f:
                vid = int(f.read().strip(), 16)
            with open(f"/sys/bus/usb/devices/{usb_bus}/idProduct") as f:
                pid = int(f.read().strip(), 16)
        except (OSError, ValueError):
            continue
        mfg = prd = ""
        try:
            with open(f"/sys/bus/usb/devices/{usb_bus}/manufacturer") as f:
                mfg = f.read().strip()
        except OSError:
            pass
        try:
            with open(f"/sys/bus/usb/devices/{usb_bus}/product") as f:
                prd = f.read().strip()
        except OSError:
            pass
        devs.append({
            "path": path,
            "vid": vid,
            "pid": pid,
            "manufacturer": mfg,
            "product": prd,
        })
    return devs


# ----------------------------------------------------------------------------
#  slcan 驱动类
# ----------------------------------------------------------------------------
class ZDTCanableSLCAN:
    """ZDT_CANable_2.0pro 的 slcan 后端驱动。

    初始化序列: C → S<n> → O；CAN Open 后绝不清空输入缓冲。
    """

    def __init__(self, port: Optional[str] = None, baudrate: int = 115_200):
        if serial is None:
            raise ImportError("缺少 pyserial，请先执行: pip install pyserial")
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional["serial.Serial"] = None
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._bitrate: Optional[int] = None
        self._data_bitrate: Optional[int] = None  # CAN FD 数据相波特率
        self._is_open = False
        self._fd_supported: Optional[bool] = None  # None=未检测, True/False
        self._started = False
        self._silent = False

    # ---- 上下文管理 ----
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---- 设备发现 ----
    @staticmethod
    def list_devices() -> List[dict]:
        return list_serial_devices()

    # ---- 串口操作 ----
    def _write(self, s: str):
        """向串口写入一条 slcan 命令（自动补 \\r）。线程安全。"""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("串口未打开")
        data = s.encode("ascii") + LINE_TERMINATOR
        with self._lock:
            self.ser.write(data)
            self.ser.flush()

    def _extract_line(self) -> Optional[str]:
        """从 _buffer 中提取一行（不含 \\r）。无完整行时返回 None。"""
        # 先处理固件错误响铃 \a (0x07)，直接丢弃
        while 0x07 in self._buffer:
            idx = self._buffer.index(0x07)
            del self._buffer[idx]
            logger.warning("slcan 固件返回错误 (BEL)，命令可能不被支持")

        if LINE_TERMINATOR not in self._buffer:
            return None
        idx = self._buffer.index(LINE_TERMINATOR)
        line = bytes(self._buffer[:idx])
        del self._buffer[:idx + 1]
        return line.decode("ascii", errors="ignore").strip()

    def _readline(self, timeout: float = 1.0) -> Optional[str]:
        """从串口读取一行（以 \\r 结尾）。线程安全。"""
        if not self.ser or not self.ser.is_open:
            return None

        with self._lock:
            # 先把串口里已有的数据读到 buffer
            while self.ser.in_waiting:
                chunk = self.ser.read(1)
                if chunk:
                    self._buffer.extend(chunk)
                else:
                    break

            line = self._extract_line()
            if line is not None:
                return line

            # 还没有完整行，做一次阻塞读取
            old_timeout = self.ser.timeout
            self.ser.timeout = timeout
            try:
                chunk = self.ser.read_until(LINE_TERMINATOR)
                if chunk:
                    self._buffer.extend(chunk)
            finally:
                self.ser.timeout = old_timeout

            return self._extract_line()

    # ---- 公共 API ----
    def open(self):
        """打开串口并初始化设备。"""
        if not self.port:
            devs = self.list_devices()
            if not devs:
                raise RuntimeError(
                    "未找到任何 ttyACM*/ttyUSB* 串口设备。请检查 USB 连接。"
                )
            self.port = devs[0]["path"]
            d = devs[0]
            logger.info("自动选择: %s  (VID=0x%04X PID=0x%04X %s %s)",
                        d["path"], d["vid"], d["pid"],
                        d["manufacturer"], d["product"])

        self.ser = serial.Serial(
            self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            rtscts=False,
            xonxoff=False,
        )

        # 清空缓冲
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        # 关键：等待设备就绪（参考 python-can _SLEEP_AFTER_SERIAL_OPEN = 2）
        # canable2 使用的 STM32 固件在 USB CDC 枚举后需要时间完成内部初始化
        time.sleep(_SLEEP_AFTER_SERIAL_OPEN)

        # 保险：先发 C 确保设备处于关闭状态
        self._write("C")
        time.sleep(0.1)
        self.ser.reset_input_buffer()

        self._is_open = True
        logger.info("slcan 端口已打开: %s @ %d", self.port, self.baudrate)

    def close(self):
        """关闭 CAN 并释放串口。"""
        if self.ser and self.ser.is_open:
            try:
                self._write("C")
                time.sleep(0.05)
            except Exception:
                pass
            self.ser.close()
        self._is_open = False
        self._started = False
        self._fd_supported = None  # 重置 FD 支持状态

    def get_version(self) -> Optional[str]:
        """读取固件版本 (V 命令)。CAN 关闭状态下调用更可靠。"""
        if not self._is_open:
            return None
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write(b"V\r")
            self.ser.flush()
            time.sleep(0.3)
            data = self.ser.read(64)
        text = data.decode("ascii", errors="ignore").strip()
        return text if text else None

    def check_fd_support(self) -> bool:
        """检测固件是否支持 CAN FD。

        发送 Y2 命令：返回 \a (BEL=0x07) 表示不支持，否则认为支持。
        很多 slcan 固件不回 \r ACK，所以不能以 \r 作为判断依据。
        """
        if self._fd_supported is not None:
            return self._fd_supported

        if not self._is_open:
            logger.warning("串口未打开，无法检测 FD 支持")
            self._fd_supported = False
            return False

        was_started = self._started
        if was_started:
            self._write("C")
            self._started = False
            time.sleep(0.1)

        # 实际测试：发送 Y2 命令，检查是否返回 BEL (0x07) 错误
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write(b"Y2\r")
            self.ser.flush()
            time.sleep(0.3)
            resp = self.ser.read(16)

        logger.info("Y2 响应: %r", resp)

        if b"\x07" in resp:
            # 固件明确返回错误 → 不支持 FD
            self._fd_supported = False
            logger.info("固件不支持 CAN FD (Y2 返回 BEL 错误)")
        else:
            # 无错误 → 支持（STM32G4 等 FDCAN 硬件）
            self._fd_supported = True
            logger.info("固件支持 CAN FD (Y2 未返回错误)")

        # 恢复 CAN 状态
        if was_started:
            with self._lock:
                self.ser.reset_input_buffer()
            self._write("S" + SLCAN_BITRATE_CODES.get(self._bitrate, "6"))
            if self._fd_supported and self._data_bitrate:
                self._write(SLCAN_DATA_BITRATE_CODES[self._data_bitrate])
            self._write("O")
            self._started = True
            time.sleep(0.1)

        return self._fd_supported

    def set_bitrate(self, bitrate: int):
        """设置 CAN 波特率。

        只在 CAN 关闭状态下有效（S 命令必须在 O 之前发）。
        如果 CAN 已 Open，会被 start() 在重新打开时应用。
        """
        if bitrate not in SLCAN_BITRATE_CODES:
            raise ValueError(
                f"slcan 不支持 {bitrate} bps。可选: "
                f"{sorted(SLCAN_BITRATE_CODES.keys())}"
            )
        self._bitrate = bitrate
        # 如果 CAN 还没 Open，立即下发 S 命令
        if self._is_open and not self._started:
            self._write("S" + SLCAN_BITRATE_CODES[bitrate])
        logger.info("已配置 bitrate = %d", bitrate)

    def set_data_bitrate(self, data_bitrate: int):
        """设置 CAN FD 数据相波特率 (Y 命令)。

        只支持 2M 和 5M。必须在 CAN 关闭状态或 start() 之前调用。
        """
        if data_bitrate not in SLCAN_DATA_BITRATE_CODES:
            raise ValueError(
                f"CAN FD 数据相不支持 {data_bitrate} bps。可选: "
                f"{sorted(SLCAN_DATA_BITRATE_CODES.keys())}"
            )
        self._data_bitrate = data_bitrate
        if self._is_open and not self._started:
            self._write(SLCAN_DATA_BITRATE_CODES[data_bitrate])
        logger.info("已配置 data_bitrate = %d", data_bitrate)

    def start(self):
        """启动 CAN 控制器。序列: C → (Y<n>) → S<n> → O"""
        if not self._is_open:
            raise RuntimeError("请先 open()")
        if self._bitrate is None:
            self._bitrate = 500_000

        # 参考 python-can 和 cangaroo 的标准初始化序列：
        # 1. C  — 确保 CAN 关闭（清除之前可能存在的错误状态）
        # 2. Y<n> — 设置 CAN FD 数据相波特率（仅固件支持时发送）
        # 3. S<n> — 设置位速率
        # 4. O — 打开 CAN
        self._write("C")
        time.sleep(0.05)
        self.ser.reset_input_buffer()  # 清掉 C 命令可能产生的响应

        if self._data_bitrate and self._fd_supported:
            self._write(SLCAN_DATA_BITRATE_CODES[self._data_bitrate])
            time.sleep(0.05)

        self._write("S" + SLCAN_BITRATE_CODES[self._bitrate])
        time.sleep(0.05)

        self._write("O")
        # O 命令后固件切换到 CAN 数据模式，不再回 ACK
        # 等一小段时间让固件完成切换
        time.sleep(0.1)

        self._started = True
        logger.info("CAN 已开启 @ %d bps (FD data: %s)",
                     self._bitrate,
                     f"{self._data_bitrate} bps" if self._data_bitrate else "关闭")

    def stop(self):
        """关闭 CAN 控制器。"""
        if not self._is_open:
            return
        self._write("C")
        self._started = False
        time.sleep(0.05)
        logger.info("CAN 已关闭")

    def recover(self):
        """从 bus-off 等错误状态恢复：重新执行 C → (Y) → S → O。"""
        if not self._is_open:
            return
        logger.warning("尝试恢复 CAN 控制器...")
        self._write("C")
        time.sleep(0.1)
        with self._lock:
            self.ser.reset_input_buffer()
        self._started = False

        if self._data_bitrate and self._fd_supported:
            self._write(SLCAN_DATA_BITRATE_CODES[self._data_bitrate])
            time.sleep(0.05)
        self._write("S" + SLCAN_BITRATE_CODES[self._bitrate])
        time.sleep(0.05)
        self._write("O")
        time.sleep(0.1)
        self._started = True
        logger.info("CAN 控制器已恢复")

    def identify(self, duration_ms: int = 1500):
        """通过切换 DTR 让设备 LED 闪烁。"""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("串口未打开")
        try:
            orig_dtr = self.ser.dtr
        except Exception:
            orig_dtr = False
        toggles = max(3, duration_ms // 200)
        gap = (duration_ms / 1000.0) / toggles
        try:
            for i in range(toggles):
                self.ser.dtr = (i % 2 == 0)
                time.sleep(gap)
        finally:
            try:
                self.ser.dtr = orig_dtr
            except Exception:
                pass
        logger.info("LED 闪烁 (DTR toggle) %d ms，共 %d 次", duration_ms, toggles)

    def set_silent(self, enable: bool) -> bool:
        """设置 M 模式 (M0=Normal, M1=Silent listen-only)。

        CAN 需要先关闭才能设 M 命令，之后重新打开。
        """
        if not self._is_open:
            raise RuntimeError("请先 open()")
        was_started = self._started
        if was_started:
            self._write("C")
            self._started = False
            time.sleep(0.05)
        self._write("M1" if enable else "M0")
        self._silent = enable
        # 重新打开 CAN（之前在运行 或 silent 模式都需要 Open 才能接收）
        if was_started or enable:
            self._write("S" + SLCAN_BITRATE_CODES[self._bitrate])
            self._write("O")
            self._started = True
            time.sleep(0.1)
        logger.info("canable2 模式: %s (silent=%s)", "M1" if enable else "M0", enable)
        return True

    def read_error_register(self) -> Optional[str]:
        """读取 CAN 错误寄存器 (E 命令)。

        E 命令需要在 CAN 关闭状态调用。
        0 = 正常, 非0 = 物理层问题。
        """
        if not self._is_open:
            return None
        was_started = self._started
        if was_started:
            self._write("C")
            self._started = False
            time.sleep(0.1)

        # 清空缓冲再发 E
        self.ser.reset_input_buffer()
        self._write("E")

        # 读取 E 响应
        time.sleep(0.3)
        data = self.ser.read(64)

        # 恢复 CAN Open
        if was_started:
            self._write("S" + SLCAN_BITRATE_CODES.get(self._bitrate, "6"))
            self._write("O")
            self._started = True
            time.sleep(0.1)

        text = data.decode("ascii", errors="ignore").strip()
        if "Error Register:" in text:
            val = text.split(":")[-1].strip()
            return val
        return text if text else None

    def send(self, frame: CANFrame):
        """发送一帧 CAN / CAN FD 报文。"""
        if not self._is_open:
            raise RuntimeError("请先 open()")
        if not self._started:
            raise RuntimeError("请先 start()")

        dlc = frame.dlc  # 使用 DLC 码（FD 帧可能是 >8 的编码）
        data_hex = frame.data.hex().upper() if frame.data else ""

        if frame.fd:
            # CAN FD 帧: d/D (无BRS) 或 b/B (有BRS)
            if frame.brs:
                cmd = "B" if frame.extended else "b"
            else:
                cmd = "D" if frame.extended else "d"
            id_s = f"{frame.can_id:08X}" if frame.extended else f"{frame.can_id:03X}"
            raw_cmd = f"{cmd}{id_s}{dlc:X}{data_hex}"
            logger.info("slcan TX FD: %s (fd=%s brs=%s dlc=%d datalen=%d)",
                        raw_cmd, frame.fd, frame.brs, dlc, len(frame.data))
            self._write(raw_cmd)
        elif frame.rtr:
            # 经典远程帧
            if frame.extended:
                self._write(f"R{frame.can_id:08X}{len(frame.data)}")
            else:
                self._write(f"r{frame.can_id:03X}{len(frame.data)}")
        else:
            # 经典数据帧
            if frame.extended:
                self._write(f"T{frame.can_id:08X}{dlc}{data_hex}")
            else:
                self._write(f"t{frame.can_id:03X}{dlc}{data_hex}")

    def receive(self, timeout: float = 1.0) -> Optional[CANFrame]:
        """从设备读取一帧（阻塞）。"""
        if not self._is_open:
            raise RuntimeError("请先 open()")
        if not self._started:
            return None

        line = self._readline(timeout=timeout)
        if line is None:
            return None
        frame = self._parse_line(line)
        if frame is None and line:
            logger.debug("slcan 未识别行: %r", line)
        elif frame and frame.fd:
            logger.debug("slcan FD 帧: dlc=%d len=%d brs=%s data=%s",
                         frame.dlc, len(frame.data), frame.brs,
                         frame.data.hex().upper()[:40])
        return frame

    @staticmethod
    def _parse_line(line: str) -> Optional[CANFrame]:
        """解析一行 slcan 文本为 CANFrame。"""
        if not line:
            return None
        head = line[0]
        rest = line[1:]

        # CAN FD 帧: b/B (有BRS), d/D (无BRS)
        if head in ("b", "B", "d", "D"):
            extended = head in ("B", "D")
            brs = head in ("b", "B")
            id_len = 8 if extended else 3
            if len(rest) < id_len + 1:
                return None
            can_id = int(rest[:id_len], 16)
            dlc_code = int(rest[id_len], 16)
            actual_len = CANFrame.dlc_to_len(dlc_code)
            data_hex = rest[id_len + 1:id_len + 1 + actual_len * 2]
            data = bytes.fromhex(data_hex) if data_hex else b""
            return CANFrame(can_id=can_id, data=data, extended=extended,
                            fd=True, brs=brs, rtr=False)

        # 经典数据帧
        if head in ("t", "T"):
            extended = head == "T"
            id_len = 8 if extended else 3
            if len(rest) < id_len + 1:
                return None
            can_id = int(rest[:id_len], 16)
            dlc = int(rest[id_len:id_len + 1], 16)
            data_hex = rest[id_len + 1:id_len + 1 + dlc * 2]
            data = bytes.fromhex(data_hex) if data_hex else b""
            return CANFrame(can_id=can_id, data=data, extended=extended, rtr=False)

        # 经典远程帧
        if head in ("r", "R"):
            extended = head == "R"
            id_len = 8 if extended else 3
            if len(rest) < id_len + 1:
                return None
            can_id = int(rest[:id_len], 16)
            dlc = int(rest[id_len:id_len + 1], 16)
            return CANFrame(can_id=can_id, data=b"", extended=extended, rtr=True)

        return None
