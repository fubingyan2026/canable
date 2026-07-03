#!/usr/bin/env python3
"""ZDT_CANable_2.0pro Python 驱动

兼容 gs_usb (candleLight) 和 slcan (CDC ACM) 两种固件模式。
构造时 backend="auto" 会自动检测。

依赖: pip install pyusb pyserial
"""

import struct
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

try:
    import usb.core
    import usb.util
except ImportError:
    raise ImportError("缺少 pyusb，请先执行: pip install pyusb")

logger = logging.getLogger("zdt_canable")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


# ----------------------------------------------------------------------------
#  USB 标识
# ----------------------------------------------------------------------------
# 所有已知的 gs_usb 兼容设备 VID/PID。
# ZDT_CANable 2.0 PRO 出厂固件通常是 canable2（github.com/normaldotcom/canable2），
# VID/PID 为 16D0:117E。
KNOWN_DEVICES = [
    (0x16D0, 0x117E, "MCS CANable2 (canable2 固件)"),
    (0x1D50, 0x606F, "candleLight 默认"),
    (0x1D50, 0x6069, "candleLight 派生"),
    (0x1D50, 0x606A, "candleLight 派生"),
    (0x1D50, 0x606B, "candleLight 派生"),
    (0x1D50, 0x606C, "candleLight 派生"),
    (0x1D50, 0x606D, "candleLight 派生"),
    (0x1D50, 0x606E, "candleLight 派生"),
    (0x1D50, 0x60AC, "cantact / CANAble (兼容)"),
    (0x1209, 0x2323, "pid.codes gs_usb"),
    (0x1209, 0x2322, "pid.codes 派生"),
    (0x16D0, 0x0FDB, "MDFLY CANable (旧版)"),
]

# ----------------------------------------------------------------------------
#  gs_usb 控制请求
# ----------------------------------------------------------------------------
GS_USB_BREQ_HOST_FORMAT     = 0
GS_USB_BREQ_BITTIMING       = 1
GS_USB_BREQ_MODE            = 2
GS_USB_BREQ_BERR            = 3
GS_USB_BREQ_BT_CONST        = 4
GS_USB_BREQ_DEVICE_CONFIG   = 5
GS_USB_BREQ_DATA_BITTIMING  = 10

# gs_host_frame 标志位
GS_CAN_FLAG_OVERFLOW = 0x01
GS_CAN_FLAG_FD       = 0x10
GS_CAN_FLAG_BRS      = 0x20
GS_CAN_FLAG_ESI      = 0x40

# gs_device_mode 标志位
GS_CAN_MODE_RESET        = 0
GS_CAN_MODE_START        = 1
GS_CAN_MODE_LISTEN_ONLY  = 0x01
GS_CAN_MODE_LOOP_BACK    = 0x02
GS_CAN_MODE_FD           = 0x100   # BIT(8)

# gs_usb HOST_FORMAT 魔数
GS_USB_HOST_FORMAT_MAGIC = 0x0000BEEF

# 帧大小
GS_USB_FRAME_SIZE    = 20   # 经典 CAN (12 头部 + 8 数据)
GS_USB_FRAME_SIZE_FD = 76   # CAN FD   (12 头部 + 64 数据)

# CAN FD DLC 映射 (DLC码 → 实际字节数)
CAN_FD_DLC_MAP = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 12, 0xA: 16, 0xB: 20, 0xC: 24, 0xD: 32, 0xE: 48, 0xF: 64,
}
# 反向映射: 字节数 → DLC码
CAN_FD_DLC_REVERSE = {v: k for k, v in CAN_FD_DLC_MAP.items()}

# CAN ID 标志位
CAN_EFF_FLAG = 0x80000000   # 扩展帧
CAN_RTR_FLAG = 0x40000000   # 远程帧
CAN_ERR_FLAG = 0x20000000   # 错误帧

# ----------------------------------------------------------------------------
#  位定时参数 — 从设备 BT_CONST 动态计算
#  默认值基于 STM32G4 FDCAN 时钟 (kazu-321 FD 移植版: 160 MHz)
#  注意：实际时钟在 _init_gsusb() 中从 BT_CONST 动态获取
#  (brp, prop_seg, phase_seg1, phase_seg2, sjw)
#  bit_rate = clk / (brp * (1 + prop_seg + phase_seg1 + phase_seg2))
# ----------------------------------------------------------------------------
DEFAULT_CAN_CLK = 160_000_000   # STM32G4 FDCAN 时钟 (kazu-321 FD 移植版)

def _calc_btr(clk: int, bitrate: int):
    """根据时钟频率和目标波特率计算位定时参数。

    返回 (brp, prop_seg, phase_seg1, phase_seg2, sjw)。
    """
    # 目标总时间份额 = clk / (bitrate * brp)
    # 先找到合适的 brp 使得 total_tq 在合理范围 (8~25)
    for brp in range(1, 1025):
        total_tq = clk / (bitrate * brp)
        if 8 <= total_tq <= 25:
            total_tq = int(total_tq)
            break
    else:
        raise ValueError(f"无法为 {bitrate} bps / {clk} Hz 计算位定时")

    # 分配: prop_seg=1, phase_seg2=max(2, total_tq//4), phase_seg1=剩余
    prop_seg = 1
    phase_seg2 = max(2, total_tq // 4)
    phase_seg1 = total_tq - 1 - prop_seg - phase_seg2
    if phase_seg1 < 1:
        phase_seg1 = 1
        phase_seg2 = total_tq - 1 - prop_seg - phase_seg1
    sjw = min(phase_seg2, 4)
    return (brp, prop_seg, phase_seg1, phase_seg2, sjw)

# 常用波特率预计算表 (170 MHz)
BTR_TABLE = {
    bitrate: _calc_btr(DEFAULT_CAN_CLK, bitrate)
    for bitrate in [10_000, 20_000, 50_000, 100_000, 125_000,
                    250_000, 500_000, 800_000, 1_000_000]
}

# 数据相位位定时 (CAN FD data phase, 170MHz 时钟)
DATA_BTR_TABLE = {
    bitrate: _calc_btr(DEFAULT_CAN_CLK, bitrate)
    for bitrate in [1_000_000, 2_000_000, 5_000_000, 8_000_000]
}


# ----------------------------------------------------------------------------
#  CAN 帧数据类
# ----------------------------------------------------------------------------
@dataclass
class CANFrame:
    """CAN 2.0 / CAN FD 帧数据类。"""
    can_id:    int                 # 仲裁 ID（11 位标准帧 或 29 位扩展帧）
    data:      bytes = b""         # 数据域（经典 CAN: 0~8, CAN FD: 0~64 字节）
    extended:  bool = False        # 是否扩展帧
    rtr:       bool = False        # 是否远程帧
    fd:        bool = False        # CAN FD 帧
    brs:       bool = False        # Bit Rate Switch（仅 FD 有效）
    esi:       bool = False        # Error State Indicator（仅 FD 有效）
    timestamp: float = 0.0         # 接收时间戳（秒）
    echo_id:   int = 0             # 用于回环匹配（发送时忽略）
    is_tx:     bool = False        # 标记该帧来自本地发送（用于 UI 区分）

    def __post_init__(self):
        if self.extended:
            if not 0 <= self.can_id <= 0x1FFFFFFF:
                raise ValueError(f"扩展帧 ID 越界: 0x{self.can_id:X}")
        else:
            if not 0 <= self.can_id <= 0x7FF:
                raise ValueError(f"标准帧 ID 越界: 0x{self.can_id:X}")
        max_len = 64 if self.fd else 8
        if len(self.data) > max_len:
            raise ValueError(f"{'CAN FD' if self.fd else '经典 CAN'} 数据不能超过 {max_len} 字节")
        if not isinstance(self.data, (bytes, bytearray)):
            self.data = bytes(self.data)

    @property
    def dlc(self) -> int:
        """返回 DLC 码。经典 CAN 直接等于 len(data)，CAN FD 使用映射表。"""
        n = len(self.data)
        if not self.fd or n <= 8:
            return n
        return CAN_FD_DLC_REVERSE.get(n, 0xF)

    @staticmethod
    def dlc_to_len(dlc: int) -> int:
        """DLC 码 → 实际字节数。"""
        return CAN_FD_DLC_MAP.get(dlc, 64)

    def to_bytes(self) -> bytes:
        """打包为 gs_host_frame。经典 CAN 20 字节，FD 76 字节。

        布局: can_id(u32) + echo_id(u32) + can_dlc(u8) + channel(u8)
              + flags(u8) + reserved(u8) + data(8 or 64 bytes)
        """
        can_id = self.can_id
        if self.extended:
            can_id |= CAN_EFF_FLAG
        if self.rtr:
            can_id |= CAN_RTR_FLAG
        flags = 0
        if self.fd:
            flags |= GS_CAN_FLAG_FD
        if self.brs:
            flags |= GS_CAN_FLAG_BRS
        if self.esi:
            flags |= GS_CAN_FLAG_ESI

        if self.fd:
            data_padded = bytes(self.data).ljust(64, b'\x00')
            return struct.pack('<IIBBBB64s',
                               can_id, self.echo_id, self.dlc, 0,
                               flags, 0, data_padded)
        else:
            data_padded = bytes(self.data).ljust(8, b'\x00')
            return struct.pack('<IIBBBB8s',
                               can_id, self.echo_id, self.dlc, 0,
                               flags, 0, data_padded)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "CANFrame":
        """从 gs_host_frame 还原成 CANFrame。经典 20 字节，FD 76 字节。"""
        if len(raw) < 12:
            return None
        can_id_full, echo_id, dlc, _channel = struct.unpack('<IIBB', raw[:10])
        flags = raw[10]
        is_fd = bool(flags & GS_CAN_FLAG_FD)
        actual_len = cls.dlc_to_len(dlc) if is_fd else min(dlc, 8)
        data_start = 12
        data = raw[data_start:data_start + actual_len]
        extended = bool(can_id_full & CAN_EFF_FLAG)
        rtr      = bool(can_id_full & CAN_RTR_FLAG)
        can_id   = can_id_full & 0x1FFFFFFF if extended else can_id_full & 0x7FF
        return cls(
            can_id=can_id,
            data=bytes(data),
            extended=extended,
            rtr=rtr,
            fd=is_fd,
            brs=bool(flags & GS_CAN_FLAG_BRS),
            esi=bool(flags & GS_CAN_FLAG_ESI),
            timestamp=time.time(),
            echo_id=echo_id,
        )

    def __str__(self) -> str:
        kind = "EFF" if self.extended else "SFF"
        tags = []
        if self.fd:
            tags.append("FD")
        if self.brs:
            tags.append("BRS")
        if self.esi:
            tags.append("ESI")
        if self.rtr:
            tags.append("RTR")
        tag_str = " ".join(tags)
        id_s = f"{self.can_id:08X}" if self.extended else f"{self.can_id:03X}"
        return f"[{id_s} {kind} {tag_str}] {self.data.hex(' ').upper()}"


# ----------------------------------------------------------------------------
#  设备驱动
# ----------------------------------------------------------------------------
class ZDTCanable:
    """ZDT_CANable_2.0pro 设备驱动，自动选择 gs_usb 或 slcan 后端。"""

    def __init__(self,
                 vid: Optional[int] = None,
                 pid: Optional[int] = None,
                 serial: Optional[str] = None,
                 port: Optional[str] = None,
                 backend: str = "auto"):
        self.vid    = vid
        self.pid    = pid
        self.serial = serial
        self.port   = port
        self.backend = backend

        # gs_usb 状态
        self.dev:    Optional[usb.core.Device] = None
        self.ep_out: Optional[usb.core.Endpoint] = None
        self.ep_in:  Optional[usb.core.Endpoint] = None

        # 公共
        self._lock       = threading.Lock()
        self._running    = False
        self._recv_thr:  Optional[threading.Thread] = None
        self._callbacks: List[Callable[[CANFrame], None]] = []
        self._overflow_cb: Optional[Callable[[], None]] = None
        self._bitrate:   Optional[int] = None
        self._data_bitrate: Optional[int] = None
        self._fd_mode:   bool = False
        self._can_clk:   int = DEFAULT_CAN_CLK
        self._feature_flags: int = 0

        # 后端分发
        self._is_slcan = False
        self._slcan:    Optional[object] = None   # ZDTCanableSLCAN 实例

    # ----------------- 上下文管理器 -----------------
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ----------------- 后端调度辅助 -----------------
    def _slcan_obj(self):
        if self._slcan is None:
            from zdt_canable_slcan import ZDTCanableSLCAN
            self._slcan = ZDTCanableSLCAN(port=self.port)
        return self._slcan

    def _delegate(self, method_name, *args, **kwargs):
        """slcan 模式下，转发到 slcan 后端。"""
        obj = self._slcan_obj()
        return getattr(obj, method_name)(*args, **kwargs)

    # ----------------- 枚举 / 打开 / 关闭 -----------------
    @staticmethod
    def list_devices() -> List[dict]:
        """列出当前所有支持的设备（合并 gs_usb 和 slcan 扫描结果）。"""
        devs: List[dict] = []

        # 1) gs_usb
        for vid, pid, _desc in KNOWN_DEVICES:
            for d in usb.core.find(find_all=True, idVendor=vid, idProduct=pid):
                # 排除 CDC ACM 类（它们走 slcan 后端）
                try:
                    if d.bDeviceClass == 0x02:
                        continue
                except Exception:
                    pass
                try:
                    mfg = usb.util.get_string(d, d.iManufacturer) or ""
                    prd = usb.util.get_string(d, d.iProduct) or ""
                    ser = usb.util.get_string(d, d.iSerialNumber) or ""
                except Exception:
                    mfg = prd = ser = ""
                devs.append({
                    "backend": "gs_usb",
                    "vid": vid, "pid": pid,
                    "manufacturer": mfg, "product": prd, "serial": ser,
                    "path": None,
                })

        # 2) slcan / CDC ACM
        try:
            from zdt_canable_slcan import list_serial_devices
            for d in list_serial_devices():
                devs.append({
                    "backend": "slcan",
                    "vid": d["vid"], "pid": d["pid"],
                    "manufacturer": d["manufacturer"], "product": d["product"],
                    "serial": "",
                    "path": d["path"],
                })
        except Exception as e:
            logger.debug("扫描 slcan 设备失败: %s", e)
        return devs

    def open(self):
        """查找并打开设备。"""
        if self.backend == "slcan":
            self._is_slcan = True
            return self._slcan_obj().open()

        if self.backend == "gs_usb":
            self._is_slcan = False
            return self._open_gsusb()

        # auto：先 gs_usb，失败再 slcan
        try:
            self._open_gsusb()
            self._is_slcan = False
            return
        except RuntimeError as e:
            logger.info("gs_usb 不可用 (%s)，尝试 slcan 后端", e)
            self._is_slcan = True
            try:
                return self._slcan_obj().open()
            except Exception as e2:
                raise RuntimeError(
                    f"gs_usb 和 slcan 后端都不可用：\n"
                    f"  gs_usb: {e}\n  slcan: {e2}"
                )

    def _open_gsusb(self):
        # 1) 精确查找
        if self.vid is not None and self.pid is not None:
            if self.serial:
                self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid,
                                         serial_number=self.serial)
            else:
                self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
            if self.dev is None:
                raise RuntimeError(
                    f"未找到 ZDT_CANable 设备 (VID=0x{self.vid:04X}, "
                    f"PID=0x{self.pid:04X})。请检查 USB 连接或 udev 权限。"
                )
        else:
            # 2) 自动扫描所有已知设备
            self.dev = None
            for vid, pid, desc in KNOWN_DEVICES:
                kwargs = dict(idVendor=vid, idProduct=pid)
                if self.serial:
                    kwargs["serial_number"] = self.serial
                dev = usb.core.find(**kwargs)
                if dev is None:
                    continue
                # 跳过 CDC ACM 类设备（它们走 slcan）
                try:
                    if dev.bDeviceClass == 0x02:
                        logger.debug("跳过 CDC ACM 设备: 0x%04X:0x%04X", vid, pid)
                        continue
                except Exception:
                    pass
                self.dev = dev
                self.vid = vid
                self.pid = pid
                logger.info("自动匹配 gs_usb: 0x%04X:0x%04X  %s", vid, pid, desc)
                break
            if self.dev is None:
                ids = ", ".join(f"0x{v:04X}:0x{p:04X}" for v, p, _ in KNOWN_DEVICES)
                raise RuntimeError(
                    f"未找到任何已知的 gs_usb 设备。已尝试: {ids}"
                )

        # 脱离内核驱动（如有）
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
                logger.info("已脱离内核驱动")
        except (usb.core.USBError, NotImplementedError) as e:
            logger.debug("脱离内核驱动失败: %s", e)

        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]

        # 找端点
        self.ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e:
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        self.ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e:
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
        )
        if self.ep_out is None or self.ep_in is None:
            raise RuntimeError("找不到所需的 USB 端点")

        try:
            mfg = usb.util.get_string(self.dev, self.dev.iManufacturer) or ""
            prd = usb.util.get_string(self.dev, self.dev.iProduct) or ""
            ser = usb.util.get_string(self.dev, self.dev.iSerialNumber) or ""
            logger.info("设备已打开: %s %s (S/N: %s)", mfg, prd, ser)
        except Exception:
            logger.info("设备已打开: %04X:%04X", self.vid, self.pid)

        # gs_usb 协议初始化
        self._init_gsusb()

    def close(self):
        """关闭并释放设备。"""
        if self._is_slcan and self._slcan is not None:
            self._slcan.close()
            return
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
        logger.info("设备已关闭")

    # ----------------- 控制传输 -----------------
    def _ctrl_out(self, req, value: int = 0, index: int = 0, data=None, timeout: int = 1000):
        bmRequestType = (usb.util.CTRL_OUT
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        if data is None:
            data = []
        return self.dev.ctrl_transfer(bmRequestType, req, value, index, data, timeout)

    def _ctrl_in(self, req, value: int = 0, index: int = 0, length: int = 64, timeout: int = 1000):
        bmRequestType = (usb.util.CTRL_IN
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        return self.dev.ctrl_transfer(bmRequestType, req, value, index, length, timeout)

    def _init_gsusb(self):
        """gs_usb 设备初始化：发送 HOST_FORMAT、查询时钟和特性。"""
        # 1) HOST_FORMAT — 告知设备主机字节序
        hfc = struct.pack('<I', GS_USB_HOST_FORMAT_MAGIC)
        self._ctrl_out(GS_USB_BREQ_HOST_FORMAT, value=1, data=hfc)

        # 2) DEVICE_CONFIG — 查询设备信息
        raw = self._ctrl_in(GS_USB_BREQ_DEVICE_CONFIG, length=12)
        if raw and len(raw) >= 12:
            data = bytes(raw)
            sw_version = struct.unpack_from('<I', data, 4)[0]
            hw_version = struct.unpack_from('<I', data, 8)[0]
            logger.info("固件版本: sw=0x%08X hw=0x%08X", sw_version, hw_version)

        # 3) BT_CONST — 查询位定时常量和 CAN 时钟
        # candlelight 固件 v2 的布局: feature(u32) + clk(u32) + tseg1_min..brp_inc
        # 标准 gs_usb 布局: clk(u32) + tseg1_min..brp_inc
        raw = self._ctrl_in(GS_USB_BREQ_BT_CONST, length=64)
        if raw and len(raw) >= 36:
            data = bytes(raw)
            fields = struct.unpack_from('<10I', data[:40])

            # 自动检测格式：第一个字段是 clk 还是 feature
            # clk 通常是 MHz 级别 (>=1_000_000)，feature 通常 < 0x10000
            first_val = fields[0]
            if first_val >= 1_000_000:
                # 标准格式: clk, tseg1_min, ...
                self._can_clk = fields[0]
                self._feature_flags = fields[8] if len(fields) > 8 else 0
                bt_info = dict(zip(
                    ['clk', 'tseg1_min', 'tseg1_max', 'tseg2_min', 'tseg2_max',
                     'sjw_max', 'brp_min', 'brp_max', 'brp_inc'],
                    fields[:9]))
            else:
                # candlelight 格式: feature, clk, tseg1_min, ...
                self._can_clk = fields[1]
                self._feature_flags = fields[0]
                bt_info = dict(zip(
                    ['feature', 'clk', 'tseg1_min', 'tseg1_max', 'tseg2_min',
                     'tseg2_max', 'sjw_max', 'brp_min', 'brp_max', 'brp_inc'],
                    fields[:10]))

            logger.info("CAN 时钟: %d Hz (%g MHz), 特性: 0x%X, BT_CONST: %s",
                        self._can_clk, self._can_clk / 1e6, self._feature_flags, bt_info)

            # 如果时钟不是默认值，重新计算 BTR 表
            if self._can_clk != DEFAULT_CAN_CLK and self._can_clk > 0:
                logger.info("时钟非默认值，重新计算位定时表")
                for bitrate in list(BTR_TABLE.keys()):
                    try:
                        BTR_TABLE[bitrate] = _calc_btr(self._can_clk, bitrate)
                    except ValueError:
                        BTR_TABLE.pop(bitrate, None)
                for bitrate in list(DATA_BTR_TABLE.keys()):
                    try:
                        DATA_BTR_TABLE[bitrate] = _calc_btr(self._can_clk, bitrate)
                    except ValueError:
                        DATA_BTR_TABLE.pop(bitrate, None)
        else:
            self._can_clk = DEFAULT_CAN_CLK
            self._feature_flags = 0
            logger.warning("无法读取 BT_CONST，使用默认时钟 %d MHz", self._can_clk / 1e6)

    # ----------------- 配置 / 启动 -----------------
    def set_bitrate(self, bitrate: int):
        """设置 CAN 波特率。"""
        if self._is_slcan:
            return self._delegate("set_bitrate", bitrate)
        if bitrate not in BTR_TABLE:
            raise ValueError(
                f"不支持的波特率 {bitrate}。可选: {sorted(BTR_TABLE.keys())}"
            )
        brp, prop_seg, phase_seg1, phase_seg2, sjw = BTR_TABLE[bitrate]
        # gs_device_bittiming: 5 x u32 (prop_seg, phase_seg1, phase_seg2, sjw, brp)
        payload = struct.pack('<IIIII', prop_seg, phase_seg1, phase_seg2, sjw, brp)
        self._ctrl_out(GS_USB_BREQ_BITTIMING, data=payload)
        self._bitrate = bitrate
        logger.info("波特率已设置: %d bps  (brp=%d seg=%d/%d sjw=%d)",
                    bitrate, brp, prop_seg + phase_seg1, phase_seg2, sjw)

    def set_data_bitrate(self, data_bitrate: int):
        """设置 CAN FD 数据相波特率。"""
        if self._is_slcan:
            return self._delegate("set_data_bitrate", data_bitrate)
        if data_bitrate not in DATA_BTR_TABLE:
            raise ValueError(
                f"不支持的数据相波特率 {data_bitrate}。可选: {sorted(DATA_BTR_TABLE.keys())}"
            )
        brp, prop_seg, phase_seg1, phase_seg2, sjw = DATA_BTR_TABLE[data_bitrate]
        payload = struct.pack('<IIIII', prop_seg, phase_seg1, phase_seg2, sjw, brp)
        try:
            self._ctrl_out(GS_USB_BREQ_DATA_BITTIMING, data=payload)
            self._data_bitrate = data_bitrate
            logger.info("数据相波特率已设置: %d bps", data_bitrate)
        except usb.core.USBError as e:
            logger.warning("设置数据相波特率失败: %s (固件可能不支持)", e)

    def get_version(self) -> Optional[str]:
        """读取固件版本。"""
        if self._is_slcan:
            return self._delegate("get_version")
        return None

    def check_fd_support(self) -> bool:
        """检测固件是否支持 CAN FD。"""
        if self._is_slcan:
            return self._delegate("check_fd_support")
        # 使用 _init_gsusb() 中缓存的特性标志
        # GS_CAN_FEATURE_FD = BIT(5)
        fd_supported = bool(self._feature_flags & (1 << 5))
        logger.info("FD 支持: %s (feature=0x%X)", fd_supported, self._feature_flags)
        return fd_supported

    def recover(self):
        """从 bus-off 等错误状态恢复。"""
        if self._is_slcan:
            return self._delegate("recover")
        # gs_usb: STOP → START
        self.stop()
        time.sleep(0.1)
        self.start()
        logger.info("CAN 控制器已恢复")

    def start(self):
        """启动 CAN 控制器。gs_usb 使用 GS_USB_BREQ_MODE 命令。"""
        if self._is_slcan:
            self._delegate("start")
            self._running = True
            return
        # gs_device_mode: mode(u32) + flags(u32)
        # mode: GS_CAN_MODE_RESET=0 / GS_CAN_MODE_START=1
        # flags: GS_CAN_MODE_LISTEN_ONLY | GS_CAN_MODE_LOOP_BACK | GS_CAN_MODE_FD ...
        # 先 RESET 确保干净状态
        self._ctrl_out(GS_USB_BREQ_MODE, data=struct.pack('<II', 0, 0))
        time.sleep(0.05)

        # START with flags
        flags = 0
        if self._fd_mode:
            flags |= GS_CAN_MODE_FD
        self._ctrl_out(GS_USB_BREQ_MODE, data=struct.pack('<II', 1, flags))
        self._running = True
        logger.info("CAN 控制器已启动 (FD=%s, flags=0x%X)", self._fd_mode, flags)

    def stop(self):
        """停止 CAN 控制器。"""
        if self._is_slcan:
            self._delegate("stop")
            self._running = False
            return
        if self._running:
            try:
                mode = GS_CAN_MODE_RESET
                self._ctrl_out(GS_USB_BREQ_MODE, data=struct.pack('<II', mode, 0))
            except usb.core.USBError as e:
                logger.warning("停止时 USB 错误: %s", e)
            self._running = False
            logger.info("CAN 控制器已停止")

    def identify(self, duration_ms: int = 1500):
        """让设备 LED 闪烁以便识别多台设备。

        - gs_usb 后端：发 GS_USB_BREQ_IDENTIFY 控制传输
        - slcan  后端：切换 DTR 让 canable2 等固件的 LED 闪烁
        """
        if self._is_slcan:
            return self._delegate("identify", duration_ms)
        self._ctrl_out(GS_USB_BREQ_IDENTIFY, value=duration_ms)

    def set_silent(self, enable: bool) -> bool:
        """打开 / 关闭 canable2 固件 M1 silent (listen-only) 模式。

        注意：canable2 slcan 固件**没有 loopback** 命令，
        silent 模式是只听不发，不能用来测 TX 回环。
        """
        if self._is_slcan:
            return self._delegate("set_silent", enable)
        # gs_usb 后端暂未实现
        logger.warning("set_silent 当前仅支持 slcan 后端")
        return False

    # ----------------- 收发 -----------------
    def send(self, frame: CANFrame, timeout: int = 1000):
        """发送单帧 CAN 报文。"""
        if self._is_slcan:
            return self._delegate("send", frame)
        if not self._running:
            raise RuntimeError("CAN 控制器未启动")
        raw = frame.to_bytes()
        with self._lock:
            self.ep_out.write(raw, timeout=timeout)
        logger.debug("TX %s", frame)

    def read_error_register(self) -> Optional[str]:
        """读取 CAN 错误寄存器 (slcan E 命令)。

        返回值: 字符串形式的错误寄存器值，或 None (gs_usb 不支持)。
        0 = 正常, 非0 = 物理层问题 (接线/终端电阻/位速率)。
        """
        if self._is_slcan:
            return self._delegate("read_error_register")
        return None

    def send_periodic(self, frame: CANFrame, interval_s: float, count: int = 0):
        """周期性发送 `count` 次，count=0 表示无限循环。"""
        deadline = 0 if count == 0 else count
        sent = 0
        while True:
            self.send(frame)
            sent += 1
            if deadline and sent >= deadline:
                break
            time.sleep(interval_s)

    def receive(self, timeout: float = 1.0) -> Optional[CANFrame]:
        """阻塞接收一帧。timeout 单位为秒，0 表示非阻塞。"""
        if self._is_slcan:
            return self._delegate("receive", timeout)
        if not self._running:
            raise RuntimeError("CAN 控制器未启动")
        try:
            # 读取 FD 帧大小（76 字节），经典帧只有 20 字节，USB 会自动处理
            data = self.ep_in.read(GS_USB_FRAME_SIZE_FD, timeout=int(timeout * 1000))
        except usb.core.USBError as e:
            # errno 110 = ETIMEDOUT (libusb timeout)
            if getattr(e, "errno", None) == 110 or "timeout" in str(e).lower():
                return None
            raise
        if not data:
            return None
        # 溢出帧：can_dlc=0, flags & GS_CAN_FLAG_OVERFLOW
        if len(data) >= 11 and data[10] & GS_CAN_FLAG_OVERFLOW:
            logger.warning("硬件接收溢出")
            if self._overflow_cb:
                self._overflow_cb()
            return None
        return CANFrame.from_bytes(bytes(data))

    # ----------------- 回调 / 监听 -----------------
    def on_receive(self, callback: Callable[[CANFrame], None]):
        """注册接收回调（监听模式下使用）。"""
        self._callbacks.append(callback)

    def on_overflow(self, callback: Callable[[], None]):
        """注册溢出回调。"""
        self._overflow_cb = callback

    def start_listening(self):
        """启动后台接收线程，把帧分发给所有回调。"""
        if not self._running:
            raise RuntimeError("CAN 控制器未启动")
        if self._recv_thr and self._recv_thr.is_alive():
            return
        self._recv_thr = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thr.start()

    def stop_listening(self):
        """停止后台接收线程。"""
        self._running = False
        if self._recv_thr:
            self._recv_thr.join(timeout=1.0)
            self._recv_thr = None

    def _recv_loop(self):
        while self._running:
            try:
                frame = self.receive(timeout=0.1)
            except Exception as e:
                if self._running:
                    logger.warning("接收异常（继续重试）: %s", e)
                time.sleep(0.1)
                continue
            if frame is None:
                continue
            for cb in self._callbacks:
                try:
                    cb(frame)
                except Exception as e:
                    logger.warning("回调异常: %s", e)


# ----------------------------------------------------------------------------
#  命令行小工具
# ----------------------------------------------------------------------------
def _cli():
    import argparse, sys, signal

    ap = argparse.ArgumentParser(
        description="ZDT_CANable_2.0pro 命令行工具（发送 / 监听）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("-b", "--bitrate", type=int, default=500_000,
                    help="CAN 波特率")
    ap.add_argument("-l", "--listen", action="store_true",
                    help="监听模式（接收并打印 CAN 帧）")
    ap.add_argument("-i", "--id", type=lambda x: int(x, 0), default=0x123,
                    help="发送帧 ID（可写 0x123 或 123）")
    ap.add_argument("-d", "--data", type=str, default="DE AD BE EF",
                    help="发送数据（十六进制，空格分隔）")
    ap.add_argument("-e", "--extended", action="store_true",
                    help="扩展帧 (29-bit ID)")
    ap.add_argument("-c", "--count", type=int, default=1,
                    help="发送次数；0 表示持续发送")
    ap.add_argument("-p", "--period", type=float, default=0.1,
                    help="发送周期（秒）")
    args = ap.parse_args()

    if not args.listen and args.count != 1:
        # 持续发送模式默认开启监听
        args.listen = False

    def stop(sig, frame):
        print("\n退出…")
        sys.exit(0)
    signal.signal(signal.SIGINT, stop)

    # 列出设备
    devs = ZDTCanable.list_devices()
    if not devs:
        print("未发现 candleLight 设备，请检查 USB 连接。")
        sys.exit(1)
    print("发现设备:")
    for i, d in enumerate(devs):
        print(f"  [{i}] {d['manufacturer']} {d['product']}  S/N={d['serial']}")

    with ZDTCanable() as bus:
        bus.set_bitrate(args.bitrate)
        bus.start()

        if args.listen:
            bus.on_receive(lambda f: print(f"RX {f}  t={f.timestamp:.6f}"))
            bus.start_listening()
            print(f"监听中 @ {args.bitrate} bps ... Ctrl-C 退出")
            signal.pause()

        # 发送模式
        data = bytes.fromhex(args.data.replace(",", " ").replace("0x", " "))
        frame = CANFrame(args.id, data, extended=args.extended)
        sent = 0
        try:
            while True:
                bus.send(frame)
                sent += 1
                print(f"TX {frame}  ({sent})")
                if args.count and sent >= args.count:
                    break
                if args.count == 1:
                    break
                time.sleep(args.period)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    _cli()
