"""捷电机 MIT 模式 CAN FD 协议层：帧构造器 + 反馈解析器。

无 Qt 依赖，可独立测试。
协议文档：juxie_canfd_cmd.md（第 2 章反馈报文、第 4 章 MIT 控制报文）
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

# ── CAN ID 基址 ──
SYNC_ID = 0x80
MIT_SINGLE_BASE = 0x110
FEEDBACK_ID_BASE = 0x300
ZERO_ID_BASE = 0x600      # 标零：CANopen SDO 写请求

# ── 控制字节位掩码 ──
BIT_ENABLE = 0x80
BIT_BRAKE = 0x40
BIT_CLEAR_ERR = 0x20
MODE_MASK = 0x1E
MODE_MIT = 0x06

# ── MIT 参数固定量程 ──
# 文档 docs/juxie_canfd_cmd.md §4.1（9 字节帧）的增益满量程
KP_MAX = 500.0       # 12bit 无符号 ↔ 0..500
KD_MAX = 5.0         # 12bit 无符号 ↔ 0..5


def _clamp_int16(v: int) -> int:
    return max(-32768, min(32767, int(v)))


def _clamp_uint16(v: int) -> int:
    return max(0, min(65535, int(v)))


def _clamp_12bit(v: int) -> int:
    return max(0, min(4095, int(v)))


def _clamp_uint8(v: int) -> int:
    return max(0, min(255, int(v)))


# ── 控制字节 ──

def build_control_byte(enable: bool, brake: bool, clear_err: bool, mode: int) -> int:
    b = 0
    if enable:
        b |= BIT_ENABLE
    if brake:
        b |= BIT_BRAKE
    if clear_err:
        b |= BIT_CLEAR_ERR
    b |= (mode << 1) & MODE_MASK
    return b & 0xFF


# ── 单位换算（标准单位 → 协议原始值）──

def _lround(value: float) -> int:
    """C 的 lroundf 语义：四舍五入，.5 远离 0（与固件 float_to_uint 一致）。"""
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def unit_to_u16(value: float, scale_max: float) -> int:
    """双极性量程 [-scale_max, +scale_max] → uint16 [0, 65535]。"""
    return _clamp_uint16(_lround((value + scale_max) / (2.0 * scale_max) * 65535.0))


def unit_to_12bit(value: float, scale_max: float) -> int:
    """双极性量程 [-scale_max, +scale_max] → 12bit [0, 4095]。"""
    return _clamp_12bit(_lround((value + scale_max) / (2.0 * scale_max) * 4095.0))


def unit_to_12bit_unipolar(value: float, scale_max: float) -> int:
    """单极性量程 [0, +scale_max] → 12bit [0, 4095]。"""
    return _clamp_12bit(_lround(value / scale_max * 4095.0))


def torque_to_raw(torque_nm: float, torque_max: float,
                  signed: bool = False) -> int:
    """力矩 → 12bit。

    默认「居中」映射：raw [0..4095] ↔ (-T_MAX..+T_MAX)，2048 为零点。
    signed=True 为「有符号」映射：raw 按 12bit 二的补码解释，0 才是零力矩。
    """
    tmax = max(1e-9, float(torque_max))
    if signed:
        v = _lround(torque_nm / tmax * 2047.0)
        return max(-2048, min(2047, v)) & 0x0FFF
    return unit_to_12bit(torque_nm, tmax)


def raw_to_torque(raw: int, torque_max: float, signed: bool = False) -> float:
    """12bit → 力矩（Nm），与 torque_to_raw 互逆。"""
    tmax = float(torque_max)
    if signed:
        v = raw - 4096 if raw >= 2048 else raw
        return v / 2047.0 * tmax
    return (raw / 4095.0 * 2.0 - 1.0) * tmax


# ── MIT 单轴控制帧构造 ──

def build_mit_single_control(dev_id: int, enable: bool, brake: bool,
                             clear_err: bool, position: int, velocity: int,
                             kp: int, kd: int, torque: int) -> bytes:
    """低层：原始值打包为 MIT 单轴控制帧 payload（9 字节）。

    12-bit 字段跨字节边界打包：
      Byte[1~2]: position  (uint16)
      Byte[3] + Byte[4]高4bit: velocity (12bit)
      Byte[4]低4bit + Byte[5]: kp (12bit)
      Byte[6] + Byte[7]高4bit: kd (12bit)
      Byte[7]低4bit + Byte[8]: torque (12bit)
    """
    ctrl = build_control_byte(enable, brake, clear_err, MODE_MIT)
    pos = _clamp_uint16(position)
    vel = _clamp_12bit(velocity)
    kp_v = _clamp_12bit(kp)
    kd_v = _clamp_12bit(kd)
    trq = _clamp_12bit(torque)

    b = bytearray(9)
    b[0] = ctrl
    b[1] = (pos >> 8) & 0xFF
    b[2] = pos & 0xFF
    b[3] = (vel >> 4) & 0xFF
    b[4] = ((vel & 0x0F) << 4) | ((kp_v >> 8) & 0x0F)
    b[5] = kp_v & 0xFF
    b[6] = (kd_v >> 4) & 0xFF
    b[7] = ((kd_v & 0x0F) << 4) | ((trq >> 8) & 0x0F)
    b[8] = trq & 0xFF
    return bytes(b)


def build_mit_control(dev_id: int, enable: bool, brake: bool,
                      clear_err: bool, pos_deg: float, vel_rpm: float,
                      kp: float, kd: float, torque_nm: float,
                      pos_max: float, vel_max: float, torque_max: float,
                      torque_raw: int | None = None,
                      torque_signed: bool = False) -> bytes:
    """高层：标准单位 → 原始值 → 打包 MIT 单轴控制帧（文档 §4.1，9 字节）。

    位置：°（±pos_max）→ uint16
    速度：RPM（±vel_max）→ 12bit
    Kp：0..500 → 12bit
    Kd：0..5 → 12bit
    力矩：Nm（±torque_max）→ 12bit；torque_raw 非空时直接使用该 12bit 原始值；
          torque_signed=True 时按有符号（0 为零点）映射
    """
    tq_raw = (_clamp_12bit(torque_raw) if torque_raw is not None
              else torque_to_raw(torque_nm, torque_max, torque_signed))
    return build_mit_single_control(
        dev_id, enable, brake, clear_err,
        unit_to_u16(pos_deg, pos_max),
        unit_to_12bit(vel_rpm, vel_max),
        unit_to_12bit_unipolar(kp, KP_MAX),
        unit_to_12bit_unipolar(kd, KD_MAX),
        tq_raw,
    )


def build_mit_single_canid(dev_id: int) -> int:
    return MIT_SINGLE_BASE | _clamp_uint8(dev_id)


# ── 电机标零（CANopen SDO 写 Index 0x2531 Sub0 = 1，当前角度置零）──
# 依据 E1_Hand_G474 service/srv_juxie_motor.c: srv_juxie_motor_zero()
#   CAN 0x600|Dev_ID，标准帧，FD+BRS，DLC 8
#   数据 23 31 25 00 01 00 00 00 = SDO 下行(4B) 写 0x2531:00 = 0x00000001
SDO_ZERO_DATA = bytes([0x23, 0x31, 0x25, 0x00, 0x01, 0x00, 0x00, 0x00])


def build_zero_canid(dev_id: int) -> int:
    """标零帧 CAN ID：0x600 | Dev_ID。"""
    return ZERO_ID_BASE | _clamp_uint8(dev_id)


# ── 反馈解析 ──

@dataclass
class FeedbackData:
    """执行器反馈报文解析结果。"""
    position: float
    speed: int
    current: int
    error_code: int
    temperature: float
    torque: float | None
    mode_feedback: int
    status: int
    enabled: bool
    brake_released: bool
    has_error: bool
    position_reached: bool


def parse_feedback(data: bytes) -> FeedbackData | None:
    """解析反馈帧（12 或 16 字节）。长度不符返回 None。"""
    if len(data) not in (12, 16):
        return None

    pos_raw = struct.unpack('>h', data[0:2])[0]
    position = pos_raw * 180.0 / 32767.0
    speed = struct.unpack('>h', data[2:4])[0]
    current = struct.unpack('>h', data[4:6])[0]
    error_code = struct.unpack('>H', data[6:8])[0]
    temp_raw = struct.unpack('>h', data[8:10])[0]
    temperature = temp_raw * 0.1

    if len(data) == 16:
        torque_raw = struct.unpack('>h', data[10:12])[0]
        torque = torque_raw * 0.05
        mode_feedback = data[14]
        status = data[15]
    else:
        torque = None
        mode_feedback = data[10]
        status = data[11]

    enabled = bool(status & 0x80)
    brake_released = bool(status & 0x40)
    has_error = bool(status & 0x20)
    position_reached = bool(status & 0x10)

    return FeedbackData(
        position=round(position, 2),
        speed=speed,
        current=current,
        error_code=error_code,
        temperature=round(temperature, 1),
        torque=round(torque, 2) if torque is not None else None,
        mode_feedback=mode_feedback,
        status=status,
        enabled=enabled,
        brake_released=brake_released,
        has_error=has_error,
        position_reached=position_reached,
    )


def build_feedback_canid(dev_id: int) -> int:
    return FEEDBACK_ID_BASE | _clamp_uint8(dev_id)
