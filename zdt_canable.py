"""CANable 2.5 ElmueSoft USB-CAN 驱动。

支持 CANable 2.5 固件的 ElmueSoft 变长协议和 Legacy 80 字节协议。
设备: VID=0x1D50, PID=0x606F, EP_IN=0x81, EP_OUT=0x02
"""
from __future__ import annotations

import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import usb.core
import usb.util

logger = logging.getLogger("zdt_canable")

# =====================================================================
#  USB 标识
# =====================================================================
CANABLE_VID = 0x1D50
CANABLE_PID = 0x606F
EP_IN  = 0x81
EP_OUT = 0x02
MAX_PACKET_SIZE = 64

# =====================================================================
#  ElmueSoft 消息类型
# =====================================================================
MSG_TxFrame  = 10
MSG_TxEcho   = 11
MSG_RxFrame  = 12
MSG_Error    = 13
MSG_String   = 14
MSG_Busload  = 15

VALID_MSG_TYPES = {MSG_TxFrame, MSG_TxEcho, MSG_RxFrame, MSG_Error, MSG_String, MSG_Busload}
MAX_ELMUE_MSG_SIZE = 128  # CAN FD 64字节 + header 约 75 字节，留安全余量

# =====================================================================
#  控制请求码 (eUsbRequest)
# =====================================================================
GS_ReqSetHostFormat     = 0
GS_ReqSetBitTiming      = 1
GS_ReqSetDeviceMode     = 2
GS_ReqGetCapabilities   = 4
GS_ReqGetDeviceVersion  = 5
GS_ReqGetTimestamp      = 6
GS_ReqIdentify          = 7
GS_ReqSetBitTimingFD    = 10
GS_ReqGetCapabilitiesFD = 11
GS_ReqSetTermination    = 12
GS_ReqGetTermination    = 13
ELM_ReqGetBoardInfo     = 20
ELM_ReqSetFilter        = 21
ELM_ReqGetLastError     = 22
ELM_ReqSetBusLoadReport = 23

# =====================================================================
#  设备标志 (eDeviceFlags)
# =====================================================================
GS_DevFlagListenOnly       = 0x0001
GS_DevFlagLoopback         = 0x0002
GS_DevFlagOneShot          = 0x0008
GS_DevFlagTimestamp        = 0x0010
GS_DevFlagIdentify         = 0x0020
GS_DevFlagCAN_FD           = 0x0100
GS_DevFlagBitTimingFD      = 0x0400
GS_DevFlagTermination      = 0x0800
ELM_DevFlagProtocolElmue   = 0x4000
ELM_DevFlagDisableTxEcho   = 0x8000

# =====================================================================
#  CAN ID 标志 (eCanIdFlags)
# =====================================================================
CAN_ID_Error  = 0x20000000
CAN_ID_RTR    = 0x40000000
CAN_ID_29Bit  = 0x80000000
CAN_MASK_11   = 0x000007FF
CAN_MASK_29   = 0x1FFFFFFF

# =====================================================================
#  帧标志 (eFrameFlags)
# =====================================================================
FRM_FDF = 0x02
FRM_BRS = 0x04
FRM_ESI = 0x08

# =====================================================================
#  错误标志 (eErrFlagsCanID)
# =====================================================================
ERID_Tx_Timeout        = 0x0001
ERID_Arbitration_lost  = 0x0002
ERID_Controller_problem = 0x0004
ERID_Protocol_violation = 0x0008
ERID_Transceiver_error = 0x0010
ERID_No_ACK_received   = 0x0020
ERID_Bus_is_off        = 0x0040
ERID_Bus_error         = 0x0080
ERID_Controller_restarted = 0x0100
ERID_CRC_Error         = 0x0200

# 错误应用标志 (eErrorAppFlags, err_data[5])
APP_CanRxFail      = 0x01
APP_CanTxFail      = 0x02
APP_CanTxOverflow   = 0x04
APP_UsbInOverflow   = 0x08
APP_CanTxTimeout    = 0x10

# 错误总线状态 (eErrorBusStatus, err_data[1] 高4位)
BUS_StatusActive  = 0x00
BUS_StatusWarning = 0x10
BUS_StatusPassive = 0x20
BUS_StatusOff     = 0x30

# 错误字节1标志 (eErrFlagsByte1)
ER1_Rx_Errors_at_warning_level = 0x04
ER1_Tx_Errors_at_warning_level = 0x08
ER1_Rx_Passive_status_reached  = 0x10
ER1_Tx_Passive_status_reached  = 0x20
ER1_Bus_is_back_active         = 0x40

# HOST_FORMAT 魔数
HOST_FORMAT_MAGIC = 0x0000BEEF

# Legacy 帧大小
LEGACY_FRAME_SIZE = 80

# CAN FD DLC 映射
CAN_FD_DLC_MAP = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64,
}

DLC_BOUNDARIES = [8, 12, 16, 20, 24, 32, 48, 64]

# =====================================================================
#  位定时预定义表
#  格式: (brp, seg1, seg2, sjw)
#  CAN时钟 = 160 MHz
#  按 PDF 2.13 建议：BRS 时使用尽可能小的预分频器，避免总线关闭
# =====================================================================
NOMINAL_BITTIMING = {
    # 87.5% sample point, 尽可能小的预分频器 (参见 PDF 2.13)
    10_000:    (80,  174, 25, 25),
    20_000:    (40,  174, 25, 25),
    50_000:    (16,  174, 25, 25),
    83_333:    (10,  167, 24, 24),
    100_000:   (8,   174, 25, 25),
    125_000:   (8,   139, 20, 20),
    250_000:   (4,   139, 20, 20),
    500_000:   (2,   139, 20, 20),
    800_000:   (1,   174, 25, 25),
    1_000_000: (1,   139, 20, 20),
}

DATA_BITTIMING = {
    # 注意：当数据波特率与标称相同时，使用与标称相同的参数以获得 "Perfect match"
    500_000:   (2,  139, 20, 20),  # 与标称 500k 相同, 87.5%
    1_000_000: (1,  139, 20, 20),  # 与标称 1M 相同, 87.5%
    2_000_000: (1,  69,  10, 10),  # 160MHz / 80 = 2M, 87.5%
    4_000_000: (1,  34,  5,  5),   # 160MHz / 40 = 4M, 87.5%
    5_000_000: (1,  27,  4,  4),   # 160MHz / 32 = 5M, 87.5%
    8_000_000: (1,  9,   10, 9),   # 160MHz / 20 = 8M, 50% (固件注释说8M用50%采样点)
}


def _pad_to_dlc(data_len: int) -> int:
    """CAN FD 数据长度按 DLC 边界向上填充。"""
    if data_len <= 8:
        return data_len
    for b in DLC_BOUNDARIES:
        if data_len <= b:
            return b
    return 64


def _data_len_to_dlc(data_len: int) -> int:
    """数据字节数 → DLC 码。"""
    if data_len <= 8:
        return data_len
    for dlc, length in sorted(CAN_FD_DLC_MAP.items()):
        if dlc > 8 and length >= data_len:
            return dlc
    return 15


def _dlc_to_data_len(dlc: int) -> int:
    """DLC 码 → 实际最大字节数。"""
    return CAN_FD_DLC_MAP.get(dlc, 64)


# =====================================================================
#  CANFrame
# =====================================================================
@dataclass
class CANFrame:
    """CAN 帧数据类。"""
    can_id:      int
    data:        bytes = b""
    extended:    bool  = False
    rtr:         bool  = False
    fd:          bool  = False
    brs:         bool  = False
    esi:         bool  = False
    timestamp:   float = 0.0
    echo_id:     int   = 0
    is_tx:       bool  = False
    _error_info: str   = ""

    def __post_init__(self):
        if not isinstance(self.data, bytes):
            self.data = bytes(self.data)

    @property
    def is_error(self) -> bool:
        return bool(self._error_info)

    @property
    def dlc(self) -> int:
        if self.fd:
            return _data_len_to_dlc(len(self.data))
        return min(len(self.data), 8)

    @staticmethod
    def dlc_to_len(dlc: int) -> int:
        return _dlc_to_data_len(dlc)

    def __str__(self) -> str:
        id_fmt = f"{self.can_id:08X}" if self.extended else f"{self.can_id:03X}"
        kind = "EFF" if self.extended else "SFF"
        parts = [kind]
        if self.fd:
            parts.append("FD")
        if self.brs:
            parts.append("BRS")
        if self.esi:
            parts.append("ESI")
        if self.rtr:
            parts.append("RTR")
        data_hex = " ".join(f"{b:02X}" for b in self.data)
        return f"[{id_fmt} {' '.join(parts)}] {data_hex}"

    def __repr__(self) -> str:
        return f"CANFrame({self})"

    # ----- ElmueSoft TX 打包 ----- #
    def to_elmue_bytes(self, marker: int = 0) -> bytes:
        """打包为 ElmueSoft kTxFrameElmue 格式。

        kTxFrameElmue: {size(u8), MSG_TxFrame(u8), flags(u8), can_id(u32), marker(u8)} + data[]
        """
        can_id_raw = self.can_id
        if self.extended:
            can_id_raw |= CAN_ID_29Bit
        if self.rtr:
            can_id_raw |= CAN_ID_RTR

        flags = 0
        if self.fd:
            flags |= FRM_FDF
        if self.brs:
            flags |= FRM_BRS
        if self.esi:
            flags |= FRM_ESI

        # CAN FD 数据按 DLC 边界填充
        raw_data = bytes(self.data)
        if self.fd:
            padded_len = _pad_to_dlc(len(raw_data))
            raw_data = raw_data.ljust(padded_len, b'\x00')
        else:
            raw_data = raw_data.ljust(min(len(raw_data), 8), b'\x00')[:8] if raw_data else b''

        size = 8 + len(raw_data)  # kHeader(2) + flags(1) + can_id(4) + marker(1) + data
        header = struct.pack('<BB', size, MSG_TxFrame)
        body = struct.pack('<BIB', flags, can_id_raw, marker)
        return header + body + raw_data

    # ----- ElmueSoft RX 解析 ----- #
    @classmethod
    def from_elmue_rx(cls, raw: bytes, has_timestamp: bool) -> "CANFrame":
        """从 ElmueSoft kRxFrameElmue 解析。"""
        offset = 2  # 跳过 kHeader
        flags = raw[offset]
        can_id_raw = struct.unpack_from('<I', raw, offset + 1)[0]
        offset += 5  # flags(1) + can_id(4)

        ts_us = 0
        if has_timestamp:
            ts_us = struct.unpack_from('<I', raw, offset)[0]
            offset += 4

        data = raw[offset:]

        extended = bool(can_id_raw & CAN_ID_29Bit)
        rtr = bool(can_id_raw & CAN_ID_RTR)
        can_id = can_id_raw & CAN_MASK_29 if extended else can_id_raw & CAN_MASK_11
        is_fd = bool(flags & FRM_FDF)
        ts = ts_us / 1_000_000.0 if ts_us else time.time()

        return cls(
            can_id=can_id, data=bytes(data), extended=extended, rtr=rtr,
            fd=is_fd, brs=bool(flags & FRM_BRS), esi=bool(flags & FRM_ESI),
            timestamp=ts, is_tx=False,
        )

    # ----- ElmueSoft TX Echo 解析 ----- #
    @classmethod
    def from_elmue_echo(cls, raw: bytes, has_timestamp: bool,
                        tx_frames: dict = None) -> "CANFrame":
        """从 ElmueSoft kTxEchoElmue 解析。

        使用 marker 匹配原始 TX 帧，重建完整帧信息。
        """
        marker = raw[2]
        ts_us = 0
        if has_timestamp and len(raw) >= 7:
            ts_us = struct.unpack_from('<I', raw, 3)[0]
        ts = ts_us / 1_000_000.0 if ts_us else time.time()

        # 如果有缓存的 TX 帧，用 marker 找回
        if tx_frames and marker in tx_frames:
            orig = tx_frames[marker]
            return cls(
                can_id=orig.can_id, data=orig.data, extended=orig.extended,
                rtr=orig.rtr, fd=orig.fd, brs=orig.brs, esi=orig.esi,
                timestamp=ts, echo_id=marker, is_tx=True,
            )

        return cls(can_id=0, data=b"", timestamp=ts, echo_id=marker, is_tx=True)

    # ----- Legacy 解析 ----- #
    @classmethod
    def from_legacy_bytes(cls, raw: bytes) -> "CANFrame":
        """从 Legacy kHostFrameLegacy (80字节) 解析。"""
        if len(raw) < 12:
            return None

        echo_id, can_id_full = struct.unpack('<II', raw[:8])
        dlc = raw[8]
        flags = raw[10]

        if dlc > 15:
            logger.warning("Legacy帧无效 (DLC=%d), 跳过", dlc)
            return None

        is_fd = bool(flags & FRM_FDF)
        actual_len = cls.dlc_to_len(dlc) if is_fd else min(dlc, 8)
        data = raw[12:12 + actual_len]

        ts = time.time()
        if is_fd and len(raw) >= 80:
            ts_us = struct.unpack_from('<I', raw, 76)[0]
            if ts_us:
                ts = ts_us / 1_000_000.0
        elif not is_fd and len(raw) >= 24:
            ts_us = struct.unpack_from('<I', raw, 20)[0]
            if ts_us:
                ts = ts_us / 1_000_000.0

        extended = bool(can_id_full & CAN_ID_29Bit)
        rtr = bool(can_id_full & CAN_ID_RTR)
        can_id = can_id_full & CAN_MASK_29 if extended else can_id_full & CAN_MASK_11

        is_error = bool(can_id_full & CAN_ID_Error)
        if is_error:
            parts = []
            if can_id_full & ERID_Bus_is_off:
                parts.append("BUS-OFF")
            if can_id_full & ERID_No_ACK_received:
                parts.append("NO-ACK")
            if can_id_full & ERID_CRC_Error:
                parts.append("CRC-ERR")
            if not parts:
                parts.append(f"ERR-0x{can_id_full & ~CAN_ID_Error:02X}")
            return cls(
                can_id=0, data=bytes([can_id_full & 0xFF]),
                timestamp=time.time(), is_tx=False,
                _error_info=" ".join(parts),
            )

        is_tx = (echo_id != 0xFFFFFFFF)
        return cls(
            can_id=can_id, data=bytes(data), extended=extended, rtr=rtr,
            fd=is_fd, brs=bool(flags & FRM_BRS), esi=bool(flags & FRM_ESI),
            timestamp=ts, echo_id=echo_id if is_tx else 0, is_tx=is_tx,
        )

    # ----- Legacy TX 打包 ----- #
    def to_legacy_bytes(self) -> bytes:
        """打包为 Legacy kHostFrameLegacy (80字节)。"""
        can_id_raw = self.can_id
        if self.extended:
            can_id_raw |= CAN_ID_29Bit
        if self.rtr:
            can_id_raw |= CAN_ID_RTR

        flags = 0
        if self.fd:
            flags |= FRM_FDF
        if self.brs:
            flags |= FRM_BRS
        if self.esi:
            flags |= FRM_ESI

        echo_id = self.echo_id if self.echo_id else 1
        dlc = self.dlc

        if self.fd:
            data_padded = bytes(self.data).ljust(64, b'\x00')
            return struct.pack('<IIBBBB64sI',
                               echo_id, can_id_raw, dlc, 0,
                               flags, 0, data_padded, 0)
        else:
            data_padded = bytes(self.data).ljust(8, b'\x00')[:8]
            return struct.pack('<IIBBBB8s',
                               echo_id, can_id_raw, dlc, 0,
                               flags, 0, data_padded)


# =====================================================================
#  ElmueSoft 消息流解析器
# =====================================================================
class _ElmueProtocol:
    """ElmueSoft 变长协议消息流解析器。"""

    def __init__(self):
        self._buffer = bytearray()
        self._has_timestamp = False
        self._tx_frames: dict = {}  # marker -> CANFrame (用于 TX echo 匹配)
        self._pending_frames: list = []

    def set_timestamp_mode(self, enabled: bool):
        self._has_timestamp = enabled

    def store_tx_frame(self, marker: int, frame: CANFrame):
        """缓存 TX 帧以便 TX echo 匹配。"""
        self._tx_frames[marker] = frame

    def clear(self):
        """清空内部缓冲区。"""
        self._buffer.clear()
        self._pending_frames.clear()
        self._tx_frames.clear()

    def feed(self, raw: bytes) -> list:
        """将 USB 读取的原始字节喂入解析器，返回解析出的 CANFrame 列表。"""
        self._buffer.extend(raw)
        frames = []
        while len(self._buffer) >= 2:
            size = self._buffer[0]
            msg_type = self._buffer[1]

            # 同步恢复: 丢弃非法 header，直到找到合法消息边界
            if size < 2 or size > MAX_ELMUE_MSG_SIZE or msg_type not in VALID_MSG_TYPES:
                self._buffer.pop(0)
                continue

            if len(self._buffer) < size:
                break

            msg = bytes(self._buffer[:size])
            del self._buffer[:size]

            frame = self._parse_message(msg, msg_type)
            if frame is not None:
                frames.append(frame)

        return frames

    def flush_frames(self) -> list:
        """返回之前解析但未消费的帧。"""
        frames = self._pending_frames
        self._pending_frames = []
        return frames

    def _parse_message(self, msg: bytes, msg_type: int) -> Optional[CANFrame]:
        logger.debug("解析消息: type=%d size=%d data=%s", msg_type, len(msg), msg.hex())
        if msg_type == MSG_RxFrame:
            return CANFrame.from_elmue_rx(msg, self._has_timestamp)
        elif msg_type == MSG_TxEcho:
            return CANFrame.from_elmue_echo(msg, self._has_timestamp, self._tx_frames)
        elif msg_type == MSG_Error:
            return self._parse_error(msg)
        elif msg_type == MSG_String:
            self._parse_string(msg)
            return None
        elif msg_type == MSG_Busload:
            self._parse_busload(msg)
            return None
        else:
            logger.warning("未知 ElmueSoft 消息类型: %d (size=%d)", msg_type, len(msg))
            return None

    def _parse_error(self, msg: bytes) -> CANFrame:
        """解析 kErrorElmue: {header(2), err_id(4), err_data(8), [timestamp(4)]}"""
        if len(msg) < 6:
            return CANFrame(can_id=0, _error_info="ERR-SHORT")

        err_id = struct.unpack_from('<I', msg, 2)[0]
        err_data = msg[6:14] if len(msg) >= 14 else b'\x00' * 8

        parts = []

        # eErrFlagsCanID
        if err_id & ERID_Bus_is_off:
            parts.append("BUS-OFF")
        if err_id & ERID_No_ACK_received:
            parts.append("NO-ACK")
        if err_id & ERID_CRC_Error:
            parts.append("CRC-ERR")
        if err_id & ERID_Tx_Timeout:
            parts.append("TX-TIMEOUT")
        if err_id & ERID_Arbitration_lost:
            parts.append("ARB-LOST")

        # err_data[1] = eErrFlagsByte1
        byte1 = err_data[1] if len(err_data) > 1 else 0
        bus_status = byte1 & 0x30
        if bus_status == BUS_StatusOff:
            parts.append("BUS-OFF")
        elif bus_status == BUS_StatusPassive:
            parts.append("ERROR-PASSIVE")
        elif bus_status == BUS_StatusWarning:
            parts.append("ERROR-WARNING")
        elif byte1 & ER1_Bus_is_back_active:
            parts.append("BACK-ACTIVE")

        # err_data[5] = eErrorAppFlags
        app_flags = err_data[5] if len(err_data) > 5 else 0
        if app_flags & APP_CanTxOverflow:
            parts.append("TX-OVERFLOW")
        if app_flags & APP_CanTxTimeout:
            parts.append("TX-TIMEOUT")
        if app_flags & APP_CanRxFail:
            parts.append("RX-FAIL")
        if app_flags & APP_CanTxFail:
            parts.append("TX-FAIL")
        if app_flags & APP_UsbInOverflow:
            parts.append("USB-OVERFLOW")

        # err_data[6] = TX error count, err_data[7] = RX error count
        tx_err = err_data[6] if len(err_data) > 6 else 0
        rx_err = err_data[7] if len(err_data) > 7 else 0
        if tx_err or rx_err:
            parts.append(f"TEC={tx_err} REC={rx_err}")

        if not parts:
            parts.append(f"ERR-0x{err_id:02X}")

        return CANFrame(
            can_id=0, data=bytes([err_id & 0xFF]),
            timestamp=time.time(), is_tx=False,
            _error_info=" ".join(parts),
        )

    def _parse_string(self, msg: bytes):
        text = msg[2:].decode('ascii', errors='ignore')
        logger.info("设备: %s", text)

    def _parse_busload(self, msg: bytes):
        if len(msg) >= 3:
            load = msg[2]
            logger.debug("总线负载: %d%%", load)


# =====================================================================
#  ZDTCanable 主驱动类
# =====================================================================
class ZDTCanable:
    """CANable 2.5 USB-CAN 适配器驱动 (ElmueSoft 协议)。"""

    def __init__(self, vid=None, pid=None, serial=None, port=None, backend=None):
        self.vid    = vid or CANABLE_VID
        self.pid    = pid or CANABLE_PID
        self.serial = serial
        # port/backend 参数保留兼容性但不使用
        self.dev:    Optional[usb.core.Device] = None
        self.ep_out: Optional[usb.core.Endpoint] = None
        self.ep_in:  Optional[usb.core.Endpoint] = None

        self._lock       = threading.Lock()
        self._running    = False
        self._fd_mode    = False
        self._bitrate:   Optional[int] = None
        self._data_bitrate: Optional[int] = None
        self._capabilities: int = 0
        self._capabilities_fd: int = 0
        self._protocol:  Optional[str] = None  # "elmue" or "legacy"
        self._parser:    Optional[_ElmueProtocol] = None
        self._marker_counter: int = 0
        self._has_timestamp: bool = False
        self._listen_only: bool = False
        self._loopback: bool = False
        self._callbacks: List[Callable[[CANFrame], None]] = []
        self._overflow_cb: Optional[Callable[[], None]] = None
        self._last_error_info: Optional[str] = None
        self._tx_blocked_until: float = 0.0

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def fd_mode(self) -> bool:
        return self._fd_mode

    @fd_mode.setter
    def fd_mode(self, value: bool):
        self._fd_mode = value

    # ================================================================
    #  静态方法: 设备枚举
    # ================================================================
    @staticmethod
    def list_devices() -> List[dict]:
        """列出所有 CANable 设备。"""
        devs = []
        for d in usb.core.find(find_all=True, idVendor=CANABLE_VID, idProduct=CANABLE_PID):
            try:
                mfg = usb.util.get_string(d, d.iManufacturer) or ""
                prd = usb.util.get_string(d, d.iProduct) or ""
                ser = usb.util.get_string(d, d.iSerialNumber) or ""
            except Exception:
                mfg = prd = ser = ""
            devs.append({
                "backend": "elmue",
                "vid": CANABLE_VID, "pid": CANABLE_PID,
                "manufacturer": mfg, "product": prd, "serial": ser,
                "path": None,
            })
        return devs

    # ================================================================
    #  设备连接与断开
    # ================================================================
    def open(self):
        """查找并打开设备。"""
        kwargs = dict(idVendor=self.vid, idProduct=self.pid)
        if self.serial:
            kwargs.setdefault("serial_number", self.serial)
        self.dev = usb.core.find(**kwargs)
        if self.dev is None:
            raise RuntimeError(f"未找到 CANable 设备 (VID=0x{self.vid:04X}, PID=0x{self.pid:04X})")

        self._setup_usb()
        self._init_device()
        self._detect_protocol()

    def close(self):
        """关闭设备。"""
        if self._running:
            try:
                self.stop()
            except Exception:
                pass
        if self.dev is not None:
            try:
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None
        self.ep_in = self.ep_out = None
        self._running = False

    def _setup_usb(self):
        """USB 配置和端点查找。"""
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (usb.core.USBError, NotImplementedError):
            pass

        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]

        self.ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == EP_IN)
        self.ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == EP_OUT)

        if self.ep_out is None:
            self.ep_out = usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                                               == usb.util.ENDPOINT_OUT)
        if self.ep_in is None:
            self.ep_in = usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                                               == usb.util.ENDPOINT_IN)

        if self.ep_out is None or self.ep_in is None:
            raise RuntimeError(f"找不到 USB 端点 (需要 EP_IN=0x81, EP_OUT=0x02)")

    def _init_device(self):
        """设备初始化: RESET + HOST_FORMAT + 读取能力。"""
        # 先 RESET (与 C++ demo 一致)
        self._reset_device()

        # GS_ReqSetHostFormat: 0xBEEF = little-endian
        self._ctrl_out_checked(GS_ReqSetHostFormat,
                               data=struct.pack('<I', HOST_FORMAT_MAGIC))

        # GS_ReqGetCapabilities
        caps = self._ctrl_in(GS_ReqGetCapabilities, length=44)
        if caps and len(caps) >= 4:
            self._capabilities = struct.unpack_from('<I', bytes(caps), 0)[0]
            logger.info("能力标志: 0x%X", self._capabilities)

        # GS_ReqGetDeviceVersion
        ver = self._ctrl_in(GS_ReqGetDeviceVersion, length=16)
        if ver and len(ver) >= 12:
            sw = struct.unpack_from('<I', bytes(ver), 4)[0]
            hw = struct.unpack_from('<I', bytes(ver), 8)[0]
            logger.info("固件版本: 0x%08X, 硬件版本: 0x%08X", sw, hw)

    def _reset_device(self):
        """发送 RESET 命令。"""
        flags = ELM_DevFlagProtocolElmue
        try:
            self._ctrl_out(GS_ReqSetDeviceMode,
                           data=struct.pack('<II', 0, flags))
            time.sleep(0.05)
        except usb.core.USBError:
            logger.debug("RESET 命令失败 (可能设备已关闭)")

    def _detect_protocol(self):
        """自动检测协议版本。"""
        if self._capabilities & ELM_DevFlagProtocolElmue:
            self._protocol = "elmue"
            self._parser = _ElmueProtocol()
            logger.info("使用 ElmueSoft 变长协议")
        else:
            self._protocol = "legacy"
            self._parser = None
            logger.info("使用 Legacy 固定长度协议 (80 字节)")

    # ================================================================
    #  USB 控制传输
    # ================================================================
    def _ctrl_out(self, req, value=0, index=0, data=None, timeout=1000):
        """发送控制 OUT 请求。"""
        bmRequestType = (usb.util.CTRL_OUT
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        if data is None:
            data = []
        return self.dev.ctrl_transfer(bmRequestType, req, value, index, data, timeout)

    def _ctrl_in(self, req, value=0, index=0, length=64, timeout=1000):
        """发送控制 IN 请求。"""
        bmRequestType = (usb.util.CTRL_IN
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        return self.dev.ctrl_transfer(bmRequestType, req, value, index, length, timeout)

    def _ctrl_out_checked(self, req, value=0, index=0, data=None, timeout=1000):
        """发送控制 OUT 请求，然后自动检查 ELM_ReqGetLastError。"""
        self._ctrl_out(req, value, index, data, timeout)
        self._check_last_error()

    def _check_last_error(self):
        """调用 ELM_ReqGetLastError 检查上一个控制 OUT 是否成功。"""
        try:
            result = self._ctrl_in(ELM_ReqGetLastError, length=1)
            if result and len(result) >= 1:
                feedback = result[0]
                if feedback != 0 and feedback != 2:
                    logger.warning("控制请求失败: eFeedback=%d", feedback)
        except usb.core.USBError:
            pass

    # ================================================================
    #  CAN 控制器生命周期
    # ================================================================
    def start(self, loopback: bool = False):
        """启动 CAN 控制器。loopback=True 启用内部回环（单设备自发自收测试）。"""
        flags = 0
        if self._protocol == "elmue":
            flags |= ELM_DevFlagProtocolElmue

        if self._listen_only:
            flags |= GS_DevFlagListenOnly

        if loopback or self._loopback:
            flags |= GS_DevFlagLoopback

        if self._fd_mode:
            flags |= GS_DevFlagCAN_FD

        # ElmueSoft: 不使用 GS_DevFlagTimestamp (减少USB流量，用软件时间戳)
        # 如需硬件时间戳可添加 GS_DevFlagTimestamp

        mode = 1  # GS_ModeStart
        payload = struct.pack('<II', mode, flags)
        self._ctrl_out_checked(GS_ReqSetDeviceMode, data=payload)

        self._has_timestamp = bool(flags & GS_DevFlagTimestamp)
        if self._parser and isinstance(self._parser, _ElmueProtocol):
            self._parser.set_timestamp_mode(self._has_timestamp)

        self._running = True
        logger.info("CAN 控制器已启动 (协议=%s, FD=%s, loopback=%s, flags=0x%X, bitrate=%s, data_bitrate=%s)",
                    self._protocol, self._fd_mode, bool(flags & GS_DevFlagLoopback),
                    flags, self._bitrate, self._data_bitrate)

    def stop(self):
        """停止 CAN 控制器。"""
        flags = 0
        if self._protocol == "elmue":
            flags |= ELM_DevFlagProtocolElmue
        try:
            self._ctrl_out_checked(GS_ReqSetDeviceMode,
                                   data=struct.pack('<II', 0, flags))
        except usb.core.USBError as e:
            logger.warning("停止时 USB 错误: %s", e)
        self._running = False
        logger.info("CAN 控制器已停止")

    def recover(self):
        """从 bus-off 等错误状态恢复。"""
        # RESET
        flags = ELM_DevFlagProtocolElmue if self._protocol == "elmue" else 0
        self._ctrl_out(GS_ReqSetDeviceMode, data=struct.pack('<II', 0, flags))
        time.sleep(0.05)

        # 清空解析器残留数据，避免 recover 后错位解析
        if self._parser is not None:
            self._parser.clear()

        # 清空 IN 端点残留数据 (多轮大读取，确保清干净)
        try:
            for _ in range(16):
                self.ep_in.read(256, timeout=10)
        except usb.core.USBError:
            pass

        # 重新设置位定时
        if self._bitrate:
            self.set_bitrate(self._bitrate)
        if self._fd_mode and self._data_bitrate:
            self.set_data_bitrate(self._data_bitrate)

        # START (保持 loopback 模式)
        self.start(loopback=self._loopback)
        self._tx_blocked_until = time.time() + 0.3
        logger.info("CAN 控制器已恢复")

    # ================================================================
    #  位定时配置
    # ================================================================
    def set_bitrate(self, bitrate: int):
        """设置 CAN 标称波特率。"""
        if bitrate not in NOMINAL_BITTIMING:
            # 尝试动态计算
            brp, seg1, seg2, sjw = self._calc_bitrate_params(bitrate)
        else:
            brp, seg1, seg2, sjw = NOMINAL_BITTIMING[bitrate]

        prop = 0
        payload = struct.pack('<IIIII', prop, seg1, seg2, sjw, brp)
        self._ctrl_out_checked(GS_ReqSetBitTiming, data=payload)
        self._bitrate = bitrate
        logger.info("标称波特率已设置: %d bps (brp=%d seg1=%d seg2=%d sjw=%d)",
                    bitrate, brp, seg1, seg2, sjw)

    def set_data_bitrate(self, data_bitrate: int):
        """设置 CAN FD 数据相波特率。"""
        if data_bitrate not in DATA_BITTIMING:
            brp, seg1, seg2, sjw = self._calc_bitrate_params(data_bitrate)
        else:
            brp, seg1, seg2, sjw = DATA_BITTIMING[data_bitrate]

        prop = 0
        payload = struct.pack('<IIIII', prop, seg1, seg2, sjw, brp)
        self._ctrl_out_checked(GS_ReqSetBitTimingFD, data=payload)
        self._data_bitrate = data_bitrate
        logger.info("数据相波特率已设置: %d bps", data_bitrate)

    def _calc_bitrate_params(self, bitrate: int):
        """动态计算位定时参数。"""
        clock = 160_000_000
        best_err = float('inf')
        best = None
        for seg1 in range(1, 33):
            for seg2 in range(1, min(seg1 + 1, 17)):
                total = 1 + seg1 + seg2
                for brp in range(1, 513):
                    calc = clock / brp / total
                    err = abs(calc - bitrate) / bitrate
                    if err < best_err:
                        best_err = err
                        best = (brp, seg1, seg2, min(seg2, 4))
                    if err < 0.001:
                        return best
        if best_err > 0.05:
            raise ValueError(f"无法计算 {bitrate} bps 的位定时参数 (误差 {best_err:.1%})")
        return best

    # ================================================================
    #  收发
    # ================================================================
    def send(self, frame: CANFrame, timeout: int = 1000):
        """发送单帧 CAN 报文。"""
        if not self._running:
            raise RuntimeError("CAN 控制器未启动")

        # TX 节流
        now = time.time()
        if now < self._tx_blocked_until:
            raise RuntimeError("CAN 控制器错误恢复中, 请稍候")

        if self._protocol == "elmue":
            self._marker_counter = (self._marker_counter + 1) & 0xFF
            if self._marker_counter == 0:
                self._marker_counter = 1
            marker = self._marker_counter
            raw = frame.to_elmue_bytes(marker=marker)
            # 缓存 TX 帧用于 echo 匹配
            if self._parser and isinstance(self._parser, _ElmueProtocol):
                self._parser.store_tx_frame(marker, frame)
        else:
            raw = frame.to_legacy_bytes()

        try:
            with self._lock:
                self.ep_out.write(raw, timeout=timeout)
                # ZLP: 如果发送长度是 64 的倍数
                if len(raw) > 0 and len(raw) % MAX_PACKET_SIZE == 0:
                    self.ep_out.write(b'', timeout=timeout)
        except usb.core.USBError as e:
            if getattr(e, 'errno', None) == 32 or 'pipe' in str(e).lower():
                logger.warning("USB Pipe error, 清除 STALL...")
                try:
                    usb.util.clear_stall(self.ep_out)
                except Exception:
                    pass
                self.recover()
                self._tx_blocked_until = time.time() + 0.5
            raise

    def send_periodic(self, frame: CANFrame, interval_s: float = 0.01, count: int = 0):
        """周期性发送 CAN 帧。count=0 表示无限发送。"""
        sent = 0
        while count == 0 or sent < count:
            self.send(frame)
            sent += 1
            if count == 0 or sent < count:
                time.sleep(interval_s)

    def receive(self, timeout: float = 1.0) -> Optional[CANFrame]:
        """阻塞接收一帧。timeout 单位为秒。"""
        if not self._running:
            raise RuntimeError("CAN 控制器未启动")

        if self._protocol == "elmue":
            return self._recv_elmue(timeout)
        else:
            return self._recv_legacy(timeout)

    def _recv_elmue(self, timeout: float = 1.0) -> Optional[CANFrame]:
        """ElmueSoft 协议接收。"""
        if self._parser is not None:
            frames = self._parser.flush_frames()
            if frames:
                return frames[0]

        try:
            data = self.ep_in.read(256, timeout=int(timeout * 1000))
        except usb.core.USBError as e:
            if getattr(e, "errno", None) == 110 or "timeout" in str(e).lower():
                return None
            if getattr(e, "errno", None) == 75 or "overflow" in str(e).lower():
                logger.debug("USB overflow, 清空端点缓冲区")
                try:
                    self.ep_in.read(256, timeout=10)
                except Exception:
                    pass
                return None
            raise

        if not data:
            return None

        raw = bytes(data)
        logger.debug("USB IN 读取 %d 字节: %s", len(raw), raw[:32].hex())
        frames = self._parser.feed(raw)
        logger.debug("解析出 %d 帧", len(frames))

        if frames:
            return frames[0]
        return None

    def _recv_legacy(self, timeout: float = 1.0) -> Optional[CANFrame]:
        """Legacy 80 字节固定长度帧接收。"""
        try:
            data = self.ep_in.read(LEGACY_FRAME_SIZE, timeout=int(timeout * 1000))
        except usb.core.USBError as e:
            if getattr(e, "errno", None) == 110 or "timeout" in str(e).lower():
                return None
            if getattr(e, "errno", None) == 75 or "overflow" in str(e).lower():
                try:
                    self.ep_in.read(LEGACY_FRAME_SIZE, timeout=10)
                except Exception:
                    pass
                return None
            raise

        if not data:
            return None

        return CANFrame.from_legacy_bytes(bytes(data))

    # ================================================================
    #  功能查询与设置
    # ================================================================
    def check_fd_support(self) -> bool:
        """检测固件是否支持 CAN FD。"""
        try:
            caps_fd = self._ctrl_in(GS_ReqGetCapabilitiesFD, length=72)
            if caps_fd and len(caps_fd) >= 4:
                self._capabilities_fd = struct.unpack_from('<I', bytes(caps_fd), 0)[0]
        except usb.core.USBError:
            pass

        fd_supported = bool((self._capabilities | self._capabilities_fd) & GS_DevFlagCAN_FD)
        fd_timing = bool((self._capabilities | self._capabilities_fd) & GS_DevFlagBitTimingFD)
        supported = fd_supported and fd_timing
        logger.info("FD 支持: %s (caps=0x%X, caps_fd=0x%X)",
                    supported, self._capabilities, self._capabilities_fd)
        return supported

    def get_version(self) -> Optional[str]:
        """读取固件版本信息。"""
        try:
            ver = self._ctrl_in(GS_ReqGetDeviceVersion, length=16)
            if ver and len(ver) >= 12:
                sw = struct.unpack_from('<I', bytes(ver), 4)[0]
                return f"0x{sw:08X}"
        except usb.core.USBError:
            pass
        return None

    def read_error_register(self) -> Optional[str]:
        """读取 CAN 错误状态 (API 兼容，新固件通过 MSG_Error 自动上报)。"""
        return self._last_error_info

    def identify(self, duration_ms: int = 1500):
        """让设备 LED 闪烁。"""
        try:
            self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 1))
        except usb.core.USBError:
            pass

    def set_silent(self, enable: bool) -> bool:
        """设置 Listen-Only 模式。"""
        was_running = self._running
        if was_running:
            self.stop()
        self._listen_only = enable
        if was_running:
            self.start()
        return True

    # ================================================================
    #  新增功能
    # ================================================================
    def set_filter(self, operation: int = 0, can_id: int = 0, mask: int = 0):
        """设置硬件 CAN ID 过滤器。

        operation: 0=清除所有, 1=11位掩码, 2=29位掩码
        """
        payload = struct.pack('<BIIII', operation, can_id, mask, 0, 0)
        self._ctrl_out_checked(ELM_ReqSetFilter, data=payload)
        logger.info("过滤器已设置: op=%d id=0x%X mask=0x%X", operation, can_id, mask)

    def get_termination(self) -> Optional[bool]:
        """读取 CAN 总线终端电阻状态。"""
        try:
            result = self._ctrl_in(GS_ReqGetTermination, length=4)
            if result and len(result) >= 4:
                return bool(struct.unpack_from('<I', bytes(result), 0)[0])
        except usb.core.USBError:
            pass
        return None

    def set_termination(self, enabled: bool):
        """设置 CAN 总线终端电阻开关。"""
        payload = struct.pack('<I', 1 if enabled else 0)
        self._ctrl_out_checked(GS_ReqSetTermination, data=payload)
        logger.info("终端电阻: %s", "开启" if enabled else "关闭")

    def set_bus_load_report(self, interval: int = 0):
        """设置总线负载报告间隔 (0=关闭, 1-100=100ms-10s)。"""
        payload = struct.pack('<B', interval)
        self._ctrl_out_checked(ELM_ReqSetBusLoadReport, data=payload)

    # ================================================================
    #  回调
    # ================================================================
    def on_receive(self, callback: Callable[[CANFrame], None]):
        self._callbacks.append(callback)

    def on_overflow(self, callback: Callable[[], None]):
        self._overflow_cb = callback

    def start_listening(self):
        """启动监听线程 (非 Qt 环境使用)。"""
        self._running = True
        self._recv_thr = threading.Thread(target=self._listen_loop, daemon=True)
        self._recv_thr.start()

    def _listen_loop(self):
        while self._running:
            try:
                frame = self.receive(timeout=0.1)
                if frame is not None:
                    for cb in self._callbacks:
                        try:
                            cb(frame)
                        except Exception:
                            pass
            except Exception as e:
                if self._running:
                    logger.warning("接收错误: %s", e)
                time.sleep(0.01)


# =====================================================================
#  命令行工具
# =====================================================================
def _cli():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    devs = ZDTCanable.list_devices()
    if not devs:
        print("未找到 CANable 设备")
        return

    print(f"发现 {len(devs)} 个设备:")
    for i, d in enumerate(devs):
        print(f"  [{i}] {d['manufacturer']} {d['product']} S/N: {d['serial']}")

    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()

        print("接收中... (Ctrl+C 退出)")
        try:
            while True:
                frame = bus.receive(timeout=1.0)
                if frame is not None:
                    print(frame)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    _cli()
