"""G0 双路扭矩传感器 CAN 协议层：帧构造 + 解析（无 Qt 依赖）。

依据 torque_sensor_can_protocol_zh.md：
- 总线：MCP2518FD，Classic CAN（非 FD），1 Mbit/s，标准帧
- 主机控制帧 DLC=7：``10 <regH> <regL> <float32 大端>``
    * 停止主动上报  0x5003 = 0.0    -> ``10 50 03 00 00 00 00``
    * 设置采样率    0x5002 = Hz     -> ``10 50 02 44 7A 00 00`` (1000.0)
    * 开启主动上报  0x5003 = 255.0  -> ``10 50 03 43 7F 00 00``
    * 硬件标零      0x4604 = 1.0    -> ``10 46 04 3F 80 00 00``
- 传感器测量帧（大端 IEEE-754 float32，单位 N·m）：
    * 新格式 0x410/0x420：前缀 ``04 00 00`` + 4 字节浮点（DLC>=7）
    * 旧格式 0x411/0x421：4 字节浮点（DLC>=4）
- 配置应答前缀：``10 50 02``（采样率）/ ``10 50 03``（上报模式）/ ``10 46 04``（标零）

本模块可独立冒烟测试：``python -m plugins.torque_sensor.protocol``。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

from canable_sdk import CANFrame

# ── 通道定义（索引 0=sensor0, 1=sensor1）──
CHANNELS = (
    {"index": 0, "name": "sensor0", "station": 1, "request_id": 0x510,
     "new_id": 0x410, "old_id": 0x411},
    {"index": 1, "name": "sensor1", "station": 2, "request_id": 0x520,
     "new_id": 0x420, "old_id": 0x421},
)
NUM_CHANNELS = len(CHANNELS)

# ── 寄存器地址与写入值 ──
REG_SAMPLE_RATE = 0x5002
REG_REPORT_MODE = 0x5003
REG_HW_ZERO = 0x4604

REPORT_STOP_VALUE = 0.0
REPORT_START_VALUE = 255.0
HW_ZERO_VALUE = 1.0
DEFAULT_SAMPLE_RATE = 1000.0

# ── 应答识别 ──
ACK_NAME_SAMPLE_RATE = "sample_rate"
ACK_NAME_REPORT_MODE = "report_mode"
ACK_NAME_HW_ZERO = "hw_zero"

_ACK_MAP = {
    (0x10, 0x50, 0x02): ACK_NAME_SAMPLE_RATE,
    (0x10, 0x50, 0x03): ACK_NAME_REPORT_MODE,
    (0x10, 0x46, 0x04): ACK_NAME_HW_ZERO,
}

# ── 测量帧格式 ──
FMT_NEW = "new"
FMT_OLD = "old"
NEW_FMT_PREFIX = b"\x04\x00\x00"

# 响应 ID -> (通道索引, 格式)
_RESP_ID_MAP = {}
for _c in CHANNELS:
    _RESP_ID_MAP[_c["new_id"]] = (_c["index"], FMT_NEW)
    _RESP_ID_MAP[_c["old_id"]] = (_c["index"], FMT_OLD)

RESPONSE_IDS = frozenset(_RESP_ID_MAP)
REQUEST_IDS = frozenset(c["request_id"] for c in CHANNELS)


# ── 帧构造 ──
def request_id(channel: int) -> int:
    return CHANNELS[channel]["request_id"]


def _write_frame_station(station: int, reg: int, value: float) -> CANFrame:
    payload = (bytes([0x10, (reg >> 8) & 0xFF, reg & 0xFF])
               + struct.pack(">f", float(value)))
    return CANFrame(can_id=station_request_id(station), data=payload,
                    extended=False, fd=False)


def _write_frame(channel: int, reg: int, value: float) -> CANFrame:
    """构造 DLC=7 的寄存器写/请求帧：``10 <regH> <regL> <float32 BE>``。"""
    return _write_frame_station(CHANNELS[channel]["station"], reg, value)


def build_stop_report(channel: int) -> CANFrame:
    return _write_frame(channel, REG_REPORT_MODE, REPORT_STOP_VALUE)


def build_start_report(channel: int) -> CANFrame:
    return _write_frame(channel, REG_REPORT_MODE, REPORT_START_VALUE)


def build_sample_rate(channel: int, hz: float) -> CANFrame:
    return _write_frame(channel, REG_SAMPLE_RATE, hz)


def build_hw_zero(channel: int) -> CANFrame:
    return _write_frame(channel, REG_HW_ZERO, HW_ZERO_VALUE)


# ── 站号扫描与设置 ID（依据 G0_Torque_SetID）──
STATION_REQ_BASE = 0x500
STATION_RESP_BASE = 0x400
STATION_STRIDE = 0x10
MAX_SENSOR_ID = 47        # request_id(47)=0x7F0 ≤ 0x7FF；站号 48 → 0x800 越界

SCAN_QUERY_DATA = bytes([0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
SET_ID_PREFIX = bytes([0x10, 0x00, 0x90])
SET_ID_OK_VALUE = struct.pack(">f", 1.0)      # 3F 80 00 00

SCAN_QUERY_WINDOW_S = 0.05   # 每个站号查询窗口 50ms
SET_ID_TIMEOUT_S = 1.0       # 改号等待写成功应答 1s


def station_valid(station: int) -> bool:
    return 1 <= int(station) <= MAX_SENSOR_ID


def station_request_id(station: int) -> int:
    return STATION_REQ_BASE + int(station) * STATION_STRIDE


def station_response_id(station: int) -> int:
    return STATION_RESP_BASE + int(station) * STATION_STRIDE


def build_scan_query(station: int) -> CANFrame:
    """DLC=8 扫描查询帧 ``04 00 00 00 00 00 00 00``（标准帧）。"""
    return CANFrame(can_id=station_request_id(station), data=SCAN_QUERY_DATA,
                    extended=False, fd=False)


def build_set_id(current: int, target: int) -> CANFrame:
    """DLC=7 改号帧 ``10 00 90 <目标站号大端 float32>``，发往当前站号。"""
    payload = SET_ID_PREFIX + struct.pack(">f", float(target))
    return CANFrame(can_id=station_request_id(current), data=payload,
                    extended=False, fd=False)


def build_stop_report_station(station: int) -> CANFrame:
    """向任意站号发送停止主动上报（用于扫描前降噪）。"""
    return _write_frame_station(station, REG_REPORT_MODE, REPORT_STOP_VALUE)


def match_scan_reply(station: int, can_id: int, data: bytes,
                     extended: bool) -> bool:
    """扫描应答：标准帧、对应响应 ID、DLC 7/8、前缀 04 00 00、有限大端 float32。"""
    if extended or can_id != station_response_id(station):
        return False
    if not data or not (7 <= len(data) <= 8):
        return False
    if data[:3] != NEW_FMT_PREFIX:
        return False
    return _decode_f32(data[3:7]) is not None


def match_set_id_ack(current: int, target: int, can_id: int, data: bytes,
                     extended: bool):
    """改号应答：True=写成功，False=协议错误，None=不相关帧。

    旧地址或新地址均可返回；前缀 ``10 00 90`` 且值为 1.0 视为成功。
    """
    if extended or not data or len(data) < 3:
        return None
    if can_id not in (station_response_id(current), station_response_id(target)):
        return None
    if data[:3] != SET_ID_PREFIX:
        return None
    if len(data) < 7 or data[3:7] != SET_ID_OK_VALUE:
        return False
    return True


# ── 应答解析 ──
def match_ack(data: bytes) -> Optional[str]:
    """匹配配置应答前缀，返回 ACK_NAME_*；否则 None。"""
    if not data or len(data) < 3:
        return None
    return _ACK_MAP.get((data[0], data[1], data[2]))


def _decode_f32(raw: bytes) -> Optional[float]:
    if len(raw) < 4:
        return None
    value = struct.unpack(">f", raw[:4])[0]
    if not math.isfinite(value):
        return None
    return value


# ── 统一分类结果 ──
@dataclass(frozen=True)
class FrameResult:
    """单帧解析结果。

    kind == "measure"：measurement，携带 fmt + value（N·m）
    kind == "ack"    ：配置应答，携带 ack 名称
    kind == "invalid"：ID 属于传感器但帧长/内容不合法
    """

    kind: str
    channel: int
    fmt: Optional[str] = None
    value: Optional[float] = None
    ack: Optional[str] = None


def classify(can_id: int, data: bytes) -> Optional[FrameResult]:
    """按 CAN ID 与数据前缀分类传感器响应帧；非传感器 ID 返回 None。"""
    info = _RESP_ID_MAP.get(can_id)
    if info is None:
        return None
    idx, fmt = info
    raw = bytes(data or b"")

    if fmt == FMT_NEW:
        # 0x410/0x420 同时承载新格式测量帧与配置应答，按前缀区分
        ack = match_ack(raw)
        if ack is not None:
            return FrameResult("ack", idx, ack=ack)
        if len(raw) < 7 or raw[:3] != NEW_FMT_PREFIX:
            return FrameResult("invalid", idx, fmt=FMT_NEW)
        value = _decode_f32(raw[3:7])
    else:
        value = _decode_f32(raw[:4]) if len(raw) >= 4 else None

    if value is None:
        return FrameResult("invalid", idx, fmt=fmt)
    return FrameResult("measure", idx, fmt=fmt, value=value)


def decode_measurement(can_id: int, data: bytes) -> Optional[Tuple[int, str, float]]:
    """便捷函数：仅取测量值，返回 (channel, fmt, mz_nm)；非测量帧 None。"""
    res = classify(can_id, data)
    if res is None or res.kind != "measure":
        return None
    return res.channel, res.fmt, res.value


# ── 通道运行时状态 ──
@dataclass
class ChannelState:
    mz_raw: Optional[float] = None      # 最新原始扭矩 N·m（未加软件零点）
    fmt: Optional[str] = None           # 最近一帧格式
    frames: int = 0                     # 有效测量帧计数
    invalid: int = 0                    # 无效帧计数
    last_rx: float = 0.0                # time.monotonic()
    reporting: str = "unknown"          # unknown / pending_on / pending_off / on / off
    pending_cmd: Optional[str] = None   # start / stop / sample_rate
    pending_since: float = 0.0
    last_ack: Optional[str] = None      # ACK_NAME_* / "timeout"
    offset: float = 0.0                 # 软件零点 N·m

    def corrected(self) -> Optional[float]:
        if self.mz_raw is None:
            return None
        return self.mz_raw + self.offset

    def reset(self) -> None:
        """清空实时数据，保留软件零点。"""
        self.mz_raw = None
        self.fmt = None
        self.frames = 0
        self.invalid = 0
        self.last_rx = 0.0
        self.reporting = "unknown"
        self.pending_cmd = None
        self.pending_since = 0.0
        self.last_ack = None


if __name__ == "__main__":  # pragma: no cover - 冒烟测试
    def _hex(frame: CANFrame) -> str:
        return " ".join(f"{b:02X}" for b in frame.data)

    assert _hex(build_stop_report(0)) == "10 50 03 00 00 00 00"
    assert _hex(build_sample_rate(1, 1000.0)) == "10 50 02 44 7A 00 00"
    assert _hex(build_start_report(0)) == "10 50 03 43 7F 00 00"
    assert _hex(build_hw_zero(1)) == "10 46 04 3F 80 00 00"
    assert request_id(0) == 0x510 and request_id(1) == 0x520

    # 新格式：sensor0 1.0 N·m
    r = classify(0x410, bytes.fromhex("040000 3F800000".replace(" ", "")))
    assert r.kind == "measure" and r.channel == 0 and abs(r.value - 1.0) < 1e-6
    # 旧格式：sensor1 -1.0 N·m
    r = classify(0x421, bytes.fromhex("BF800000"))
    assert r.kind == "measure" and r.channel == 1 and abs(r.value + 1.0) < 1e-6
    # 应答：上报模式 / 采样率 / 标零
    assert match_ack(bytes.fromhex("10500300")) == ACK_NAME_REPORT_MODE
    assert match_ack(bytes.fromhex("10500200")) == ACK_NAME_SAMPLE_RATE
    assert match_ack(bytes.fromhex("10460400")) == ACK_NAME_HW_ZERO
    assert classify(0x410, bytes.fromhex("10500300")).kind == "ack"
    # 无效：DLC 不足 / NaN
    assert classify(0x410, bytes.fromhex("040000")).kind == "invalid"
    assert classify(0x411, bytes.fromhex("7FC00000")).kind == "invalid"
    # 非传感器 ID
    assert classify(0x123, b"\x00") is None

    # ── 站号扫描 / 设置 ID ──
    assert station_request_id(1) == 0x510 and station_response_id(1) == 0x410
    assert station_request_id(2) == 0x520 and station_response_id(2) == 0x420
    assert station_request_id(47) == 0x7F0 and station_request_id(48) > 0x7FF
    assert station_valid(1) and station_valid(47)
    assert not station_valid(0) and not station_valid(48)

    q = build_scan_query(3)
    assert q.can_id == 0x530 and not q.extended
    assert q.data == bytes([4, 0, 0, 0, 0, 0, 0, 0])

    s = build_set_id(1, 2)
    assert s.can_id == 0x510 and len(s.data) == 7 and _hex(s) == "10 00 90 40 00 00 00"
    s = build_set_id(2, 1)
    assert s.can_id == 0x520 and _hex(s) == "10 00 90 3F 80 00 00"

    good = bytes.fromhex("0400003F800000")
    assert match_scan_reply(1, 0x410, good, False)
    assert not match_scan_reply(1, 0x410, good, True)      # 扩展帧拒绝
    assert not match_scan_reply(1, 0x411, good, False)     # 旧格式 ID 不匹配
    assert not match_scan_reply(1, 0x410, bytes.fromhex("040000"), False)  # DLC 不足

    ok = bytes.fromhex("1000903F800000")
    assert match_set_id_ack(1, 2, 0x410, ok, False) is True   # 旧地址应答
    assert match_set_id_ack(1, 2, 0x420, ok, False) is True   # 新地址应答
    assert match_set_id_ack(1, 2, 0x410, bytes.fromhex("10009000000000"), False) is False
    assert match_set_id_ack(1, 2, 0x430, ok, False) is None   # 非相关 ID
    assert match_set_id_ack(1, 2, 0x410, bytes.fromhex("1050030000"), False) is None

    print("torque_sensor protocol OK")
