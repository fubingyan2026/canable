"""主电源板 CAN 上报协议 — 解码 / 编码。

依据 protocol_master.md（主电源板 → 主机 CAN 上报协议）：
- 所有上报帧固定 8 字节（DLC=8）、标准 11-bit ID、多字节字段小端
- 0x001 系统状态每 100ms 自动上报；0x011–0x015 电池帧仅在主机发送
  0x001 控制帧（7 字节）指定 feedback_select 位后才回复

本模块不依赖 Qt，可独立冒烟测试。
范围：仅监控 + 数据请求（feedback_select），不含输出控制。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional, Tuple

from canable_sdk import CANFrame

# ── CAN ID ──
HOST_CTRL_ID = 0x001   # 主机 → 主电源板 控制/请求帧（7 字节）
SYS_ID       = 0x001   # 主电源板 → 主机 系统状态（8 字节）
BASE_ID      = 0x011   # 电池基础（容量/循环/充电标志）
VOLT_CURR_ID = 0x012   # 电池电压 + 电流
VERSION_ID   = 0x013   # 电池硬件/软件版本
ERROR_ID     = 0x014   # 双电池故障码
LEVEL_ID     = 0x015   # 故障等级 + 预警 + 温度

# feedback_select 位 → 请求的帧
FEEDBACK_BITS = [
    (0, BASE_ID),
    (1, VOLT_CURR_ID),
    (2, VERSION_ID),
    (3, ERROR_ID),
    (4, LEVEL_ID),
]
ALL_FEEDBACK_MASK = sum(1 << b for b, _ in FEEDBACK_BITS)  # 0x1F

# ── 位名表（字段名是稳定标识符，widget 映射到 i18n key）──
# (byte, bit, name)：bytes1-3 的电源轨错误 + byte5 的模拟输入/上电时序
RAIL_BITS: Tuple[Tuple[int, int, str], ...] = (
    (1, 0, "err_vin"), (1, 1, "err_vin_dcdc"), (1, 2, "err_12v_int"), (1, 3, "err_5v_int"),
    (1, 4, "err_12v_ext"), (1, 5, "err_24v_ext"), (1, 6, "err_12v_user"), (1, 7, "err_24v_user"),
    (2, 0, "err_24v_comp"), (2, 1, "err_power"), (2, 2, "err_motor"), (2, 3, "err_chg_out"),
    (2, 4, "err_hsd1_12v"), (2, 5, "err_hsd2_12v"), (2, 6, "err_hsd3_12v"), (2, 7, "err_dbr"),
    (3, 0, "err_hsd1_24v"), (3, 1, "err_hsd2_24v"), (3, 2, "err_hsd3_24v"), (3, 3, "err_lsd1_24v"),
    (3, 4, "err_lsd2_24v"), (3, 5, "err_fan0"), (3, 6, "err_fan1"),
    # byte3 bit7 = byte3_fixed1（协议固定为 1，非错误），不在此表
    (5, 0, "a_in1_io"), (5, 1, "a_in2_io"), (5, 2, "a_in3_io"),
    (5, 3, "seq_vin_fault"), (5, 4, "seq_chg_fault"), (5, 5, "seq_motor_fault"),
)
# byte4 = 8 路 NTC 温度错误（每路 1 bit），整体聚合显示，不在此表展开

# 电池1 故障位（字节 0-3，单 bit）
BAT1_FAULT_BITS: Tuple[Tuple[int, int, str], ...] = (
    (0, 0, "cell_ov"), (0, 1, "total_ov"), (0, 2, "fully_charged"), (0, 3, "cell_uv"), (0, 4, "total_uv"),
    (1, 0, "short_circuit"), (1, 1, "dischg_oc"), (1, 2, "chg_oc"),
    (2, 0, "chg_ov_temp"), (2, 1, "dischg_ov_temp"), (2, 2, "mos_ov_temp"),
    (2, 3, "amb_ov_temp"), (2, 4, "amb_low_temp"),
    (3, 0, "temp_sensor_fail"), (3, 1, "volt_sensor_fail"), (3, 2, "dischg_mos_fail"),
    (3, 3, "chg_mos_fail"), (3, 4, "cell_imbalance"),
)
# 电池2 故障位（字节 4-7）；字节4 为 2-bit 编码字段，其余单 bit
BAT2_FAULT_BITS: Tuple[Tuple[int, int, int, str], ...] = (
    (4, 0, 2, "chg_temp_prot"), (4, 2, 2, "dischg_temp_prot"), (4, 4, 2, "chg_temp_warn"),
    (4, 6, 2, "dischg_temp_warn"),
    (5, 0, 1, "chg_ov_prot"), (5, 1, 1, "chg_ov_hw"), (5, 2, 1, "chg_ov_second"),
    (5, 3, 1, "dischg_uv_prot"), (5, 4, 1, "dischg_uv_hw"),
    (6, 0, 1, "chg_oc_prot"), (6, 1, 1, "short_circuit"), (6, 2, 1, "dischg_oc_prot"),
    (6, 3, 1, "dischg_oc_second"), (6, 4, 1, "dischg_oc_hw"), (6, 5, 1, "hw_defected"),
    (7, 0, 1, "chg_ov_warn"), (7, 1, 1, "dischg_uv_warn"), (7, 2, 1, "chg_oc_warn"),
    (7, 3, 1, "dischg_oc_warn"), (7, 4, 1, "chg_fet_fail"), (7, 5, 1, "dischg_fet_fail"),
    (7, 6, 1, "fuse_blown"),
)


# ── 数据模型 ──
@dataclass(frozen=True)
class SystemStatus:                       # 0x001
    stop_key_state: bool                  # byte0 bit0 急停按下
    battery_key_state: bool               # byte0 bit1 电池开关
    battery_charging: bool                # byte0 bit2 任一电池充电中
    battery_temp_error: bool              # byte0 bit3 电池温度异常
    device_online_slaver: bool            # byte0 bit4 副电源管理控制板在线
    device_online_dual: bool              # byte0 bit5 双电池控制板在线
    device_online_bat1: bool              # byte0 bit6 电池1 在线
    device_online_bat2: bool              # byte0 bit7 电池2 在线
    rail_errors: dict                     # 全部 RAIL_BITS 位名 -> bool
    ntc_bits: int                         # byte4 8 路 NTC 错误位掩码
    bat1_soc: int                         # byte6 0-100%
    bat2_soc: int                         # byte7 0-100%


@dataclass(frozen=True)
class BatBase:                            # 0x011（SOC 已由 0x001 上报，本帧不含）
    bat1_capacity: int                    # mAh（raw * 256）
    bat2_capacity: int
    bat1_cycle: int
    bat2_cycle: int
    bat1_charging: bool                   # byte6 bit0
    bat2_charging: bool                   # byte6 bit1


@dataclass(frozen=True)
class BatVoltCurr:                        # 0x012
    bat1_voltage: float                   # V（0.1V 精度）
    bat2_voltage: float
    bat1_current: float                   # A（0.1A，正=放电）
    bat2_current: float


@dataclass(frozen=True)
class BatVersion:                         # 0x013
    bat1_hw: int
    bat1_sw: int
    bat2_hw: int
    bat2_sw: int


@dataclass(frozen=True)
class BatError:                           # 0x014
    bat1_faults: Tuple[str, ...]
    bat2_faults: Tuple[str, ...]


@dataclass(frozen=True)
class BatLevel:                           # 0x015
    bat1_warnings: int
    bat1_fault_level: int                 # 0=正常 1=轻微 2=严重 3=致命
    bat2_fault_level: int
    bat2_warnings: int
    bat1_temp: int                        # °C（int8）
    bat2_temp: int


@dataclass
class PowerState:
    """聚合视图，widget 渲染的数据源。按帧增量更新。"""
    sys: Optional[SystemStatus] = None
    base: Optional[BatBase] = None
    volt_curr: Optional[BatVoltCurr] = None
    version: Optional[BatVersion] = None
    err: Optional[BatError] = None
    level: Optional[BatLevel] = None
    last_rx: float = 0.0                  # time.monotonic()


# ── 解码器 ──
def parse_system_status(data: bytes) -> Optional[SystemStatus]:
    if data is None or len(data) < 8:
        return None
    b0 = data[0]
    rail = {name: bool((data[byte] >> bit) & 1) for byte, bit, name in RAIL_BITS}
    return SystemStatus(
        stop_key_state=bool((b0 >> 0) & 1),
        battery_key_state=bool((b0 >> 1) & 1),
        battery_charging=bool((b0 >> 2) & 1),
        battery_temp_error=bool((b0 >> 3) & 1),
        device_online_slaver=bool((b0 >> 4) & 1),
        device_online_dual=bool((b0 >> 5) & 1),
        device_online_bat1=bool((b0 >> 6) & 1),
        device_online_bat2=bool((b0 >> 7) & 1),
        rail_errors=rail,
        ntc_bits=data[4],
        bat1_soc=data[6],
        bat2_soc=data[7],
    )


def parse_bat_base(data: bytes) -> Optional[BatBase]:
    if data is None or len(data) < 8:
        return None
    return BatBase(
        bat1_capacity=struct.unpack_from("<H", data, 0)[0] * 256,
        bat2_capacity=struct.unpack_from("<H", data, 2)[0] * 256,
        bat1_cycle=data[4],
        bat2_cycle=data[5],
        bat1_charging=bool((data[6] >> 0) & 1),
        bat2_charging=bool((data[6] >> 1) & 1),
    )


def parse_bat_volt_curr(data: bytes) -> Optional[BatVoltCurr]:
    if data is None or len(data) < 8:
        return None
    return BatVoltCurr(
        bat1_voltage=struct.unpack_from("<H", data, 0)[0] / 10.0,
        bat2_voltage=struct.unpack_from("<H", data, 2)[0] / 10.0,
        bat1_current=struct.unpack_from("<h", data, 4)[0] / 10.0,
        bat2_current=struct.unpack_from("<h", data, 6)[0] / 10.0,
    )


def parse_bat_version(data: bytes) -> Optional[BatVersion]:
    if data is None or len(data) < 8:
        return None
    return BatVersion(
        bat1_hw=struct.unpack_from("<H", data, 0)[0],
        bat1_sw=struct.unpack_from("<H", data, 2)[0],
        bat2_hw=struct.unpack_from("<H", data, 4)[0],
        bat2_sw=struct.unpack_from("<H", data, 6)[0],
    )


def _collect_faults(data: bytes) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    # BAT1_FAULT_BITS 用字节 0-3，BAT2_FAULT_BITS 用绝对字节 4-7
    f1 = tuple(name for byte, bit, name in BAT1_FAULT_BITS if ((data[byte] >> bit) & 1))
    f2 = tuple(
        name for byte, bit, width, name in BAT2_FAULT_BITS
        if ((data[byte] >> bit) & ((1 << width) - 1)) != 0
    )
    return f1, f2


def parse_bat_error(data: bytes) -> Optional[BatError]:
    if data is None or len(data) < 8:
        return None
    f1, f2 = _collect_faults(data)
    return BatError(bat1_faults=f1, bat2_faults=f2)


def parse_bat_level(data: bytes) -> Optional[BatLevel]:
    if data is None or len(data) < 8:
        return None
    return BatLevel(
        bat1_warnings=struct.unpack_from("<H", data, 0)[0],
        bat1_fault_level=data[2] & 0x03,
        bat2_fault_level=data[3] & 0x03,
        bat2_warnings=struct.unpack_from("<H", data, 4)[0],
        bat1_temp=struct.unpack_from("<b", data, 6)[0],
        bat2_temp=struct.unpack_from("<b", data, 7)[0],
    )


DECODERS = {
    SYS_ID: parse_system_status,
    BASE_ID: parse_bat_base,
    VOLT_CURR_ID: parse_bat_volt_curr,
    VERSION_ID: parse_bat_version,
    ERROR_ID: parse_bat_error,
    LEVEL_ID: parse_bat_level,
}


# ── 请求帧 ──
def build_request_frame(feedback_select: int) -> CANFrame:
    """7 字节 0x001 控制帧。RGB/蜂鸣器/输出控制全 0（仅监控）。"""
    payload = bytes([feedback_select & 0xFF, 0, 0, 0, 0, 0, 0])
    return CANFrame(can_id=HOST_CTRL_ID, data=payload, extended=False, fd=False)
