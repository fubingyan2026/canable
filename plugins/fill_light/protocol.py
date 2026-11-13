"""claw_ctrl CAN protocol V1.3: fill-light control and board status query.

Reference: claw_ctrl/docs/can-protocol.md.
No Qt dependency. All frames are standard CAN FD, DLC 8, BRS off.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from canable_sdk import CANFrame

REQUEST_ID = 0x220
STATUS_ID = 0x221
BITRATE = 1_000_000
STATUS_TIMEOUT = 1.5
MAX_LEVEL = 1000


@dataclass(frozen=True)
class BoardStatus:
    motor_state: int
    level: int
    uptime_ms: int


def build_light_control(level: int) -> CANFrame:
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= MAX_LEVEL:
        raise ValueError("PWM level must be an integer in 0..1000")
    return CANFrame(can_id=REQUEST_ID, data=struct.pack('<BBH4x', 1, 1, level),
                    extended=False, fd=True, brs=False)


def build_status_query() -> CANFrame:
    return CANFrame(can_id=REQUEST_ID, data=b'\x01' + bytes(7),
                    extended=False, fd=True, brs=False)


def parse_status(frame: CANFrame) -> BoardStatus | None:
    if (frame.can_id != STATUS_ID or frame.is_tx or frame.is_error or frame.rtr
            or frame.extended or not frame.fd or frame.brs or len(frame.data) != 8):
        return None
    version, motor_state, level, uptime_ms = struct.unpack('<BBHI', frame.data)
    if version != 1 or motor_state > 4 or level > MAX_LEVEL:
        return None
    return BoardStatus(motor_state, level, uptime_ms)
