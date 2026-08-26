"""捷电机 MIT 模式 CAN FD 协议层：帧构造器 + 反馈解析器。

无 Qt 依赖，可独立测试。
协议文档：juxie_canfd_cmd.md（第 2 章反馈报文、第 4 章 MIT 控制报文）
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# ── CAN ID 基址 ──
SYNC_ID = 0x80
MIT_SINGLE_BASE = 0x110
FEEDBACK_ID_BASE = 0x300

# ── 控制字节位掩码 ──
BIT_ENABLE = 0x80
BIT_BRAKE = 0x40
BIT_CLEAR_ERR = 0x20
MODE_MASK = 0x1E
MODE_MIT = 0x06

# ── MIT 参数固定量程 ──
KP_MAX = 500.0
KD_MAX = 5.0


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

def unit_to_u16(value: float, scale_max: float) -> int:
    """双极性量程 [-scale_max, +scale_max] → uint16 [0, 65535]。"""
    return _clamp_uint16(int(round((value + scale_max) / (2.0 * scale_max) * 65535.0)))


def unit_to_12bit(value: float, scale_max: float) -> int:
    """双极性量程 [-scale_max, +scale_max] → 12bit [0, 4095]。"""
    return _clamp_12bit(int(round((value + scale_max) / (2.0 * scale_max) * 4095.0)))


def unit_to_12bit_unipolar(value: float, scale_max: float) -> int:
    """单极性量程 [0, +scale_max] → 12bit [0, 4095]。"""
    return _clamp_12bit(int(round(value / scale_max * 4095.0)))


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
                      pos_max: float, vel_max: float, torque_max: float) -> bytes:
    """高层：标准单位 → 原始值 → 打包 MIT 单轴控制帧。

    位置：°（±pos_max）→ uint16
    速度：RPM（±vel_max）→ 12bit
    Kp：无单位 [0, 500] → 12bit
    Kd：无单位 [0, 5]   → 12bit
    力矩：Nm（±torque_max）→ 12bit
    """
    return build_mit_single_control(
        dev_id, enable, brake, clear_err,
        unit_to_u16(pos_deg, pos_max),
        unit_to_12bit(vel_rpm, vel_max),
        unit_to_12bit_unipolar(kp, KP_MAX),
        unit_to_12bit_unipolar(kd, KD_MAX),
        unit_to_12bit(torque_nm, torque_max),
    )


def build_mit_single_canid(dev_id: int) -> int:
    return MIT_SINGLE_BASE | _clamp_uint8(dev_id)


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
