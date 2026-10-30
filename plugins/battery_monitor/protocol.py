"""合壹电池 BMS CAN 协议：多帧包组装、BCC、命令构造与响应解析（无 Qt 依赖）。

依据 docs/合壹电池CAN通讯协议中英文对照.md：
- CAN 2.0B 标准帧（11 bit），250 kbps
- 包结构：``0x0001`` 起始 → N×``0x0002`` 数据(≤8B) → ``0x0003`` 结束
- 命令域：``EA D1 <addr> 04 FF <cmd> <bcc> F5``，BCC = XOR(byte[3..5])
- 响应域：``EA D1 <addr> <len> FF <cmd> <data...> <bcc> F5``，数据域从 byte[6] 起
- BCC 范围：从"后续数据长度"字节到结束字节之前（含）

本模块可独立自测：``python -m plugins.battery_monitor.protocol``。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

from canable_sdk import CANFrame

# ── 帧 ID ──
ID_START = 0x0001
ID_DATA = 0x0002
ID_END = 0x0003
PACKET_IDS = frozenset((ID_START, ID_DATA, ID_END))

# ── 帧内常量 ──
HEAD = 0xEA
PRODUCT = 0xD1
TAIL = 0xF5
CMD_HI = 0xFF
DEFAULT_ADDR = 0x01
ADDR_MIN = 0x01
ADDR_MAX = 0x0F

# ── 命令码 ──
CMD_VOLTAGE = 0x02
CMD_STATUS = 0x03
CMD_SOC = 0x04
CMD_BATTERY_ID = 0x11
CMD_DISCHARGE_ON = 0x19
CMD_DISCHARGE_OFF = 0x1A
CMD_CHARGE_ON = 0x1B
CMD_CHARGE_OFF = 0x1C

POLL_COMMANDS = (CMD_VOLTAGE, CMD_STATUS, CMD_SOC, CMD_BATTERY_ID)


def bcc(data: bytes) -> int:
    """按位异或校验。"""
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def build_command(addr: int, cmd: int) -> bytes:
    """构造 8 字节命令数据域：EA D1 addr 04 FF cmd bcc F5。

    BCC 覆盖"后续数据长度"到命令低字节（即 04 FF cmd），不含地址。
    """
    body = bytes([0x04, CMD_HI, cmd & 0xFF])
    return (bytes([HEAD, PRODUCT, addr & 0xFF]) + body
            + bytes([bcc(body), TAIL]))


def build_command_frames(addr: int, cmd: int) -> List[CANFrame]:
    """起始帧 → 数据帧 → 结束帧（3 帧，标准帧，Classic CAN）。"""
    payload = build_command(addr, cmd)
    return [
        CANFrame(can_id=ID_START, data=bytes(8), extended=False, fd=False),
        CANFrame(can_id=ID_DATA, data=payload, extended=False, fd=False),
        CANFrame(can_id=ID_END, data=bytes(8), extended=False, fd=False),
    ]


@dataclass
class Assembler:
    """把 0x0001/0x0002/0x0003 三帧序列拼成完整包。"""

    buf: bytearray = field(default_factory=bytearray)
    active: bool = False

    def reset(self) -> None:
        self.buf = bytearray()
        self.active = False

    def feed(self, can_id: int, data: bytes) -> Optional[bytes]:
        if can_id == ID_START:
            self.buf = bytearray()
            self.active = True
            return None
        if can_id == ID_DATA:
            if not self.active:       # 容忍缺失起始帧
                self.active = True
            self.buf.extend(bytes(data or b""))
            return None
        if can_id == ID_END:
            packet = bytes(self.buf) if self.active else None
            self.reset()
            if not packet:
                return None
            # 数据帧按 8 字节对齐，末帧常带 0x00 填充；结束字节固定为 0xF5（非零），
            # 因此可安全去掉尾部填充。
            return packet.rstrip(b"\x00")
        return None


@dataclass
class Reply:
    addr: int
    cmd: int
    data: bytes
    raw: bytes
    bcc_ok: bool


def parse_reply(packet: bytes) -> Optional[Reply]:
    """校验并拆出 addr / cmd / 数据域。

    部分 BMS 固件的长包（0x02/0x04）末尾可能缺少 F5/BCC 或被填充截断，
    这里兼容两种情况：
      - 末字节为 0xF5：正常包，data = packet[6:-2]
      - 末字节不是 0xF5：视为截断包，data = packet[6:]
        （多出的 BCC 字节由具体解析器按固定偏移忽略）
    """
    if not packet or len(packet) < 6:
        return None
    if packet[0] != HEAD or packet[1] != PRODUCT:
        return None

    if len(packet) >= 8 and packet[-1] == TAIL:
        data = packet[6:-2]
        bcc_ok = bcc(packet[3:-2]) == packet[-2]
    else:
        data = packet[6:]
        bcc_ok = False

    return Reply(addr=packet[2], cmd=packet[5], data=bytes(data),
                 raw=bytes(packet), bcc_ok=bcc_ok)


# ── 4.1 电压数据 ──
@dataclass
class VoltageData:
    cell_count: int
    temp_count: int
    total_count: int
    cells_mv: List[int]
    header: int = 3          # 实际电压起始相对偏移（3=文档表，2=示例固件）

    @property
    def pack_mv(self) -> int:
        return sum(self.cells_mv)

    def max_cell(self) -> Optional[int]:
        return max(self.cells_mv) if self.cells_mv else None

    def min_cell(self) -> Optional[int]:
        return min(self.cells_mv) if self.cells_mv else None


def parse_voltage(data: bytes) -> Optional[VoltageData]:
    """解析电压包。

    文档表头为 3 字节（串数/温度探头数/总串数），但文档自带示例中电压从第 2 字节之后
    开始。这里两种都尝试，取"所有单体电压都落在合理区间"的那种。
    """
    if len(data) < 4:
        return None
    count = data[0]
    if not 1 <= count <= 32:
        return None
    temp_count = data[1] if len(data) > 1 else 0
    for header in (3, 2):
        if header + 2 * count > len(data):
            continue
        cells = []
        ok = True
        for i in range(count):
            off = header + 2 * i
            value = (data[off] << 8) | data[off + 1]
            if not 500 <= value <= 6000:      # 0.5V ~ 6V 合理单体区间
                ok = False
                break
            cells.append(value)
        if ok:
            total = data[2] if (header == 3 and len(data) > 2) else count
            return VoltageData(cell_count=count, temp_count=temp_count,
                               total_count=total, cells_mv=cells, header=header)
    return None


# ── 4.2 电流与状态 ──
@dataclass
class StatusData:
    flags: int
    current_raw: int
    over_voltage: int
    under_voltage: int
    temp_protect: int
    other_protect: int
    cell_temps: List[int] = field(default_factory=list)   # 已换算 ℃
    mos_temp: Optional[int] = None
    ambient_temp: Optional[int] = None
    balance: bytes = b""
    sw_version: Optional[int] = None
    mos_status: Optional[int] = None
    failure: Optional[int] = None
    alarm1: Optional[int] = None
    alarm2: Optional[int] = None

    @property
    def discharging(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def charging(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def key_on(self) -> bool:
        return bool(self.flags & 0x80)

    def current_ma(self, offset_raw: int = 0) -> float:
        """电流（mA）。文档：无符号、单位 10mA，需按板型减偏置。"""
        return (self.current_raw - offset_raw) * 10.0

    def max_temp(self) -> Optional[int]:
        values = list(self.cell_temps)
        if self.mos_temp is not None:
            values.append(self.mos_temp)
        if self.ambient_temp is not None:
            values.append(self.ambient_temp)
        return max(values) if values else None


def parse_status(data: bytes) -> Optional[StatusData]:
    if len(data) < 8:
        return None
    status = StatusData(
        flags=data[0],
        current_raw=(data[1] << 8) | data[2],
        over_voltage=data[3],
        under_voltage=data[4],
        temp_protect=data[5],
        other_protect=data[6],
    )
    n = data[7]
    idx = 8
    for _ in range(n):
        if idx >= len(data):
            break
        status.cell_temps.append(data[idx] - 40)
        idx += 1
    if status.flags & 0x10 and idx < len(data):
        status.mos_temp = data[idx] - 40
        idx += 1
    if status.flags & 0x20 and idx < len(data):
        status.ambient_temp = data[idx] - 40
        idx += 1
    status.balance = bytes(data[idx:idx + 3])
    idx += 3
    if idx < len(data):
        status.sw_version = data[idx]
        idx += 1
    if idx < len(data):
        status.mos_status = data[idx]
        idx += 1
    if idx < len(data):
        status.failure = data[idx]
        idx += 1
    if idx < len(data):
        status.alarm1 = data[idx]
        idx += 1
    if idx < len(data):
        status.alarm2 = data[idx]
    return status


# ── 4.3 电量（SOC）与容量 ──
@dataclass
class SocData:
    soc: Optional[int] = None
    cycles: Optional[int] = None
    design_mah: Optional[int] = None
    full_mah: Optional[int] = None
    remain_mah: Optional[int] = None
    discharge_min: Optional[int] = None
    charge_min: Optional[int] = None
    charge_interval_h: Optional[int] = None
    max_charge_interval_h: Optional[int] = None
    total_voltage_cv: Optional[int] = None      # 10 mV
    max_cell_mv: Optional[int] = None
    min_cell_mv: Optional[int] = None
    hw_version: Optional[int] = None

    @property
    def total_voltage_v(self) -> Optional[float]:
        return None if self.total_voltage_cv is None else self.total_voltage_cv / 100.0


def _u16(data: bytes, off: int) -> Optional[int]:
    if off + 1 >= len(data):
        return None
    return (data[off] << 8) | data[off + 1]


def _u32(data: bytes, hi_off: int, lo_off: int) -> Optional[int]:
    hi = _u16(data, hi_off)
    lo = _u16(data, lo_off)
    if hi is None or lo is None:
        return None
    return (hi << 16) | lo


def parse_soc(data: bytes) -> Optional[SocData]:
    if len(data) < 2:
        return None
    soc = SocData(soc=data[1] if 0 <= data[1] <= 100 else None)
    soc.cycles = _u16(data, 3)
    soc.design_mah = _u32(data, 6, 9)
    soc.full_mah = _u32(data, 12, 15)
    soc.remain_mah = _u32(data, 18, 21)
    soc.discharge_min = _u16(data, 24)
    soc.charge_min = _u16(data, 27)
    soc.charge_interval_h = _u16(data, 30)
    soc.max_charge_interval_h = _u16(data, 32)
    soc.total_voltage_cv = _u16(data, 41)
    soc.max_cell_mv = _u16(data, 43)
    soc.min_cell_mv = _u16(data, 45)
    if len(data) > 48:
        soc.hw_version = data[48]
    return soc


# ── 4.4 电池编号 ──
def parse_battery_id(data: bytes) -> Optional[str]:
    if len(data) < 1:
        return None
    n = data[0]
    if not 1 <= n <= 31:
        return None
    raw = data[1:1 + n]
    try:
        return raw.decode("ascii", errors="replace").strip()
    except Exception:
        return None


def describe(cmd: int) -> str:
    return {
        CMD_VOLTAGE: "voltage",
        CMD_STATUS: "status",
        CMD_SOC: "soc",
        CMD_BATTERY_ID: "id",
    }.get(cmd, f"0x{cmd:02X}")


if __name__ == "__main__":  # pragma: no cover - self test
    # 命令帧（文档 §5 示例：电压请求）
    frame = build_command(DEFAULT_ADDR, CMD_VOLTAGE)
    assert frame.hex(" ").upper() == "EA D1 01 04 FF 02 F9 F5", frame.hex(" ")
    assert build_command(DEFAULT_ADDR, CMD_STATUS)[6] == 0xF8
    assert build_command(DEFAULT_ADDR, CMD_SOC)[6] == 0xFF
    assert build_command(DEFAULT_ADDR, CMD_BATTERY_ID)[6] == 0xEA
    assert bcc(bytes([0x04, 0xFF, 0x02])) == 0xF9

    # 组装：文档 §5 响应（6 个数据帧 + 起止帧）
    asm = Assembler()
    frames = [
        (0x0001, bytes(8)),
        (0x0002, bytes.fromhex("EAD10127FF020F06")),
        (0x0002, bytes.fromhex("0B4E0E9C0E5F0E84")),
        (0x0002, bytes.fromhex("0E0A0E5A0E8F0EA0")),
        (0x0002, bytes.fromhex("0EA00E8B0EB00E92")),
        (0x0002, bytes.fromhex("0E7D0EB60E730E73")),
        (0x0002, bytes.fromhex("38F5000000000000")),
        (0x0003, bytes(8)),
    ]
    packet = None
    for cid, payload in frames:
        packet = asm.feed(cid, payload) or packet
    assert packet is not None
    reply = parse_reply(packet)
    assert reply is not None and reply.cmd == CMD_VOLTAGE
    volts = parse_voltage(reply.data)
    assert volts is not None and volts.cells_mv[0] == 0x0B4E, volts
    print("voltage packet: %s cells, first=%d mV, header=%d" % (
        len(volts.cells_mv), volts.cells_mv[0], volts.header))

    # 状态包（自造，按文档表）
    st = parse_status(bytes([0x33, 0x00, 0x64, 0, 0, 0, 0, 2,
                             25 + 40, 26 + 40, 35 + 40, 24 + 40,
                             0, 0, 0, 0x12, 0x06, 0, 0x01, 0x00]))
    assert st is not None
    assert st.charging and st.discharging
    assert st.cell_temps == [25, 26] and st.mos_temp == 35 and st.ambient_temp == 24
    assert st.current_ma() == 1000.0 and st.sw_version == 0x12
    print("status packet ok: current=%.0f mA temps=%s" % (
        st.current_ma(), st.cell_temps))

    # SOC 包（字段按文档偏移）
    buf = bytearray(52)
    buf[0] = 0x01
    buf[1] = 87
    buf[3:5] = struct.pack(">H", 123)
    buf[6:8] = struct.pack(">H", 0x0001)
    buf[9:11] = struct.pack(">H", 0x86A0)        # 100000 mAh
    buf[12:14] = struct.pack(">H", 0x0001)
    buf[15:17] = struct.pack(">H", 0x86A0)
    buf[18:20] = struct.pack(">H", 0x0000)
    buf[21:23] = struct.pack(">H", 0x4E20)       # 20000 mAh
    buf[41:43] = struct.pack(">H", 5120)         # 51.20 V
    buf[43:45] = struct.pack(">H", 3300)
    buf[45:47] = struct.pack(">H", 3200)
    buf[48] = 3
    soc = parse_soc(bytes(buf))
    assert soc.soc == 87 and soc.cycles == 123
    assert soc.design_mah == 100000 and soc.remain_mah == 20000
    assert abs(soc.total_voltage_v - 51.2) < 1e-6
    assert soc.max_cell_mv == 3300 and soc.min_cell_mv == 3200
    print("soc packet ok: %d%% cycles=%d design=%d mAh pack=%.2f V" % (
        soc.soc, soc.cycles, soc.design_mah, soc.total_voltage_v))

    # 编号包
    idata = bytes([5]) + b"BAT01"
    assert parse_battery_id(idata) == "BAT01"
    print("battery id ok")
    print("battery_monitor protocol OK")
