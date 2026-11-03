"""柯力扭矩传感器 CAN V1.2 协议：命令构造与回包解析（无 Qt 依赖）。

依据 docs/柯力扭矩传感器CAN协议帧V1.2.md（正文 1~19 节）：
- CAN 2.0 标准数据帧，1 Mbps；请求与响应 ID 相同 = 0x521 + Add
- 多字节数据大端（MSB 在前）：U16 / U32 / float32
- 无应用层校验

本模块可独立自测：``python -m plugins.keli_torque.protocol``。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional

from canable_sdk import CANFrame

# ── ID 与地址 ──
ID_BASE = 0x521
ADDR_MIN = 1
ADDR_MAX = 31
DEFAULT_ADDR = 1

# ── 命令首字节 ──
B_ACK = 0x41
B_SET = 0x57
B_QUERY = 0x51
B_DATA = 0x44
B_CAL = 0x43
B_ZERO = 0x5A
B_RESET = 0x52

# ── 取数模式 ──
MODE_STOP = 0x00
MODE_SINGLE = 0x01
MODE_CONTINUOUS = 0xFF

# ── 通用应答状态 ──
ACK_OK = 0x00
ACK_BAD_CMD = 0x01
ACK_BAD_PARAM = 0x02
ACK_STORE_FAIL = 0x03

ACK_TEXT = {
    ACK_OK: "ok",
    ACK_BAD_CMD: "bad_cmd",
    ACK_BAD_PARAM: "bad_param",
    ACK_STORE_FAIL: "store_fail",
}

# ── 分度值（0x00..0x06 → N）──
SCALE_OPTIONS = (
    (0x00, 0.1), (0x01, 0.2), (0x02, 0.5), (0x03, 1.0),
    (0x04, 2.0), (0x05, 5.0), (0x06, 10.0),
)
DEFAULT_SCALE_CODE = 0x03

# ── 滤波 ──
FILTER_MIN, FILTER_MAX, DEFAULT_FILTER = 0, 5, 0

# ── AD 参数 ──
AD_RATES = (2400, 1200, 600, 300, 150, 75)
AD_GAINS = (128, 64, 32, 16, 1)
DEFAULT_AD_RATE = 2400
DEFAULT_AD_GAIN = 1

# ── 自动发数间隔：raw = ms × 10 ──
INTERVAL_UNIT = 10
INTERVAL_MIN_MS = 1
INTERVAL_MAX_MS = 2000
DEFAULT_INTERVAL_MS = 10


def can_id(addr: int) -> int:
    """请求/响应共用的标准帧 ID：0x521 + Add。"""
    return ID_BASE + int(addr)


def frame(addr: int, payload: bytes) -> CANFrame:
    """构造一帧标准 Classic CAN 数据帧（本协议请求/响应均为单帧）。"""
    return CANFrame(can_id=can_id(addr), data=bytes(payload),
                    extended=False, fd=False, brs=False)


# ── 取数 ──
def build_start_continuous(addr: int) -> bytes:
    """开始连续取力值：44 02 FF。"""
    return bytes([B_DATA, 0x02, MODE_CONTINUOUS])


def build_single_read(addr: int) -> bytes:
    """单次取力值：44 02 01。"""
    return bytes([B_DATA, 0x02, MODE_SINGLE])


def build_stop(addr: int) -> bytes:
    """停止取数：44 02 00。"""
    return bytes([B_DATA, 0x02, MODE_STOP])


def build_read_ad(addr: int) -> bytes:
    """读取 AD 码值（单次）：44 01 01。"""
    return bytes([B_DATA, 0x01, MODE_SINGLE])


# ── 归零 / 标定 ──
def build_zero_calibrate(addr: int) -> bytes:
    """零点标定：43 01（通用应答）。"""
    return bytes([B_CAL, 0x01])


def build_zero_save(addr: int) -> bytes:
    """开机置零（当前值记为零，断电保存）：5A 01。"""
    return bytes([B_ZERO, 0x01])


def build_zero_temp(addr: int) -> bytes:
    """按键置零（当前值记为零，断电不保存）：5A 02。"""
    return bytes([B_ZERO, 0x02])


def build_full_scale(addr: int, load: int) -> bytes:
    """满程标定（U32 载荷）：43 02 + U32。v1 不提供 UI。"""
    return bytes([B_CAL, 0x02]) + struct.pack(">I", int(load) & 0xFFFFFFFF)


def build_reset(addr: int) -> bytes:
    """重启传感器：52 42（无应答）。"""
    return bytes([B_RESET, 0x42])


# ── 参数写入 ──
def build_set_addr(addr: int, new_addr: int) -> bytes:
    """设置传感器地址：57 01 + Add。"""
    return bytes([B_SET, 0x01, int(new_addr) & 0xFF])


def build_set_scale(addr: int, code: int) -> bytes:
    """设置分度值：57 02 + code。"""
    return bytes([B_SET, 0x02, int(code) & 0xFF])


def build_set_filter(addr: int, level: int) -> bytes:
    """设置滤波等级：57 03 + level。"""
    return bytes([B_SET, 0x03, int(level) & 0xFF])


def build_set_ad(addr: int, rate: int, gain: int) -> bytes:
    """设置 AD 参数：57 06 + U16 采样率 + U8 增益。"""
    return (bytes([B_SET, 0x06])
            + struct.pack(">H", int(rate) & 0xFFFF)
            + bytes([int(gain) & 0xFF]))


def build_set_interval_raw(addr: int, raw: int) -> bytes:
    """设置自动发数间隔：57 07 + U16（raw = ms × 10）。"""
    return bytes([B_SET, 0x07]) + struct.pack(">H", int(raw) & 0xFFFF)


def build_set_interval(addr: int, ms: int) -> bytes:
    return build_set_interval_raw(addr, ms_to_raw(ms))


# ── 参数查询 ──
def build_query_addr(addr: int) -> bytes:
    return bytes([B_QUERY, 0x01])


def build_query_scale(addr: int) -> bytes:
    return bytes([B_QUERY, 0x02])


def build_query_filter(addr: int) -> bytes:
    return bytes([B_QUERY, 0x03])


def build_query_ad(addr: int) -> bytes:
    return bytes([B_QUERY, 0x06])


def build_query_interval(addr: int) -> bytes:
    return bytes([B_QUERY, 0x07])


def build_query_version(addr: int) -> bytes:
    return bytes([B_QUERY, 0x09])


# ── 单位换算 ──
def ms_to_raw(ms: float) -> int:
    """毫秒 → 发数间隔 raw（raw = ms × 10，夹取 1~2000 ms）。"""
    ms = max(INTERVAL_MIN_MS, min(INTERVAL_MAX_MS, float(ms)))
    return int(round(ms * INTERVAL_UNIT))


def raw_to_ms(raw: int) -> float:
    return raw / float(INTERVAL_UNIT)


def scale_code_to_n(code: int) -> Optional[float]:
    for value, nm in SCALE_OPTIONS:
        if value == code:
            return nm
    return None


def scale_n_to_code(nm: float) -> int:
    best = min(SCALE_OPTIONS, key=lambda item: abs(item[1] - float(nm)))
    return best[0]


# ── 回包解析 ──
@dataclass(frozen=True)
class VersionInfo:
    type_code: int
    version: int
    year: int
    month: int
    day: int

    @property
    def date_text(self) -> str:
        return "%04d-%02d-%02d" % (2000 + self.year, self.month, self.day)

    @property
    def has_date(self) -> bool:
        return bool(self.month and self.day)


@dataclass(frozen=True)
class Parsed:
    """回包解析结果。kind 取值见下方常量。"""

    kind: str
    status: Optional[int] = None        # ack
    value: Optional[float] = None       # force (N)
    raw_int: Optional[int] = None       # ad 码值
    addr: Optional[int] = None
    byte_val: Optional[int] = None      # 分度值 code / 滤波等级
    interval_raw: Optional[int] = None
    rate: Optional[int] = None
    gain: Optional[int] = None
    version: Optional[VersionInfo] = None


K_ACK = "ack"
K_FORCE = "force"
K_AD = "ad"
K_ADDR = "addr"
K_SCALE = "scale"
K_FILTER = "filter"
K_ADPARAMS = "adparams"
K_INTERVAL = "interval"
K_VERSION = "version"
K_INVALID = "invalid"


def _u16(data: bytes, off: int) -> int:
    return (data[off] << 8) | data[off + 1]


def parse(data: bytes) -> Optional[Parsed]:
    """解析一帧传感器回包；不认识的帧返回 None。"""
    if not data or len(data) < 2:
        return None
    b0, b1 = data[0], data[1]

    if b0 == B_ACK:
        return Parsed(K_ACK, status=b1 & 0xFF)

    if b0 == B_DATA:
        if b1 == 0x02:
            if len(data) < 6:
                return Parsed(K_INVALID, byte_val=0x02)
            value = struct.unpack(">f", data[2:6])[0]
            if not math.isfinite(value):
                return Parsed(K_INVALID, byte_val=0x02)
            return Parsed(K_FORCE, value=value)
        if b1 == 0x01:
            if len(data) < 6:
                return Parsed(K_INVALID, byte_val=0x01)
            return Parsed(K_AD, raw_int=struct.unpack(">i", data[2:6])[0])
        return None

    if b0 == B_QUERY:
        if b1 == 0x01:
            if len(data) < 3:
                return None
            return Parsed(K_ADDR, addr=data[2] & 0xFF)
        if b1 == 0x02:
            if len(data) < 3:
                return None
            return Parsed(K_SCALE, byte_val=data[2] & 0xFF)
        if b1 == 0x03:
            if len(data) < 3:
                return None
            return Parsed(K_FILTER, byte_val=data[2] & 0xFF)
        if b1 == 0x06:
            if len(data) < 5:
                return None
            return Parsed(K_ADPARAMS, rate=_u16(data, 2), gain=data[4] & 0xFF)
        if b1 == 0x07:
            if len(data) < 4:
                return None
            return Parsed(K_INTERVAL, interval_raw=_u16(data, 2))
        if b1 == 0x09:
            if len(data) < 4:
                return None
            year = data[4] if len(data) > 4 else 0
            month = data[5] if len(data) > 5 else 0
            day = data[6] if len(data) > 6 else 0
            return Parsed(K_VERSION, version=VersionInfo(
                type_code=data[2] & 0xFF, version=data[3] & 0xFF,
                year=year, month=month, day=day))
        return None

    return None


if __name__ == "__main__":  # pragma: no cover - 自测
    A = DEFAULT_ADDR

    def hx(b):
        return " ".join("%02X" % x for x in b)

    # 主机命令字节
    assert hx(build_start_continuous(A)) == "44 02 FF"
    assert hx(build_single_read(A)) == "44 02 01"
    assert hx(build_stop(A)) == "44 02 00"
    assert hx(build_read_ad(A)) == "44 01 01"
    assert hx(build_zero_calibrate(A)) == "43 01"
    assert hx(build_zero_save(A)) == "5A 01"
    assert hx(build_zero_temp(A)) == "5A 02"
    assert hx(build_full_scale(A, 100)) == "43 02 00 00 00 64"
    assert hx(build_reset(A)) == "52 42"
    assert hx(build_set_addr(A, 5)) == "57 01 05"
    assert hx(build_query_addr(A)) == "51 01"
    assert hx(build_set_scale(A, 3)) == "57 02 03"
    assert hx(build_query_scale(A)) == "51 02"
    assert hx(build_set_filter(A, 2)) == "57 03 02"
    assert hx(build_query_filter(A)) == "51 03"
    assert hx(build_set_ad(A, 2400, 1)) == "57 06 09 60 01"
    assert hx(build_query_ad(A)) == "51 06"
    assert hx(build_set_interval(A, 10)) == "57 07 00 64"
    assert hx(build_query_interval(A)) == "51 07"
    assert hx(build_query_version(A)) == "51 09"
    assert can_id(1) == 0x522 and can_id(31) == 0x540
    assert frame(1, b"\x52\x42").fd is False

    # 换算
    assert ms_to_raw(10) == 100 and raw_to_ms(100) == 10.0
    assert ms_to_raw(0) == 10 and ms_to_raw(9999) == 20000
    assert scale_code_to_n(0x03) == 1.0 and scale_n_to_code(2.0) == 0x04

    # 回包解析
    p = parse(bytes([0x41, 0x00]));   assert p.kind == K_ACK and p.status == 0
    p = parse(bytes([0x41, 0x02]));   assert p.kind == K_ACK and p.status == 2
    p = parse(bytes.fromhex("44023F800000")); assert p.kind == K_FORCE and abs(p.value - 1.0) < 1e-6
    p = parse(bytes.fromhex("4402BF800000")); assert p.kind == K_FORCE and abs(p.value + 1.0) < 1e-6
    p = parse(bytes.fromhex("44027FC00000")); assert p.kind == K_INVALID   # NaN
    p = parse(bytes.fromhex("4401FFFFFF9C")); assert p.kind == K_AD and p.raw_int == -100
    p = parse(bytes.fromhex("44023F80"));     assert p.kind == K_INVALID   # DLC 不足
    p = parse(bytes.fromhex("510105"));       assert p.kind == K_ADDR and p.addr == 5
    p = parse(bytes.fromhex("510203"));       assert p.kind == K_SCALE and p.byte_val == 3
    p = parse(bytes.fromhex("510302"));       assert p.kind == K_FILTER and p.byte_val == 2
    p = parse(bytes.fromhex("5106096001"));   assert p.kind == K_ADPARAMS and p.rate == 2400 and p.gain == 1
    p = parse(bytes.fromhex("51070064"));     assert p.kind == K_INTERVAL and raw_to_ms(p.interval_raw) == 10.0
    p = parse(bytes.fromhex("5109010118071E"))
    assert p.kind == K_VERSION
    assert p.version.type_code == 0x01 and p.version.version == 1
    assert p.version.date_text == "2024-07-30", p.version.date_text
    assert parse(bytes.fromhex("5201")) is None
    assert parse(b"") is None

    print("keli_torque protocol OK")
