"""Wire encodings for the Liangzhi CAN Simple and CANopen protocols."""
from __future__ import annotations

import configparser
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import struct

from canable_sdk import CANFrame


MANUAL_ASSETS = Path(__file__).resolve().parents[2] / "docs" / "良质关节驱动协议手册" / "图片和附件"


@dataclass(frozen=True)
class Command:
    name: str
    zh: str
    fmt: str = ""
    fields: tuple[str, ...] = ()


COMMANDS = {
    0x02: Command("Estop", "紧急停止"),
    0x03: Command("Get_Error", "读取详细故障", "B", ("Error_Type",)),
    0x06: Command("Set_Axis_Node_ID", "设置节点 ID", "I", ("Node_ID (0–63)",)),
    0x07: Command("Set_Axis_State", "设置轴状态", "I", ("Axis_Requested_State",)),
    0x0B: Command("Set_Controller_Mode", "设置控制模式", "II", ("Control_Mode", "Input_Mode")),
    0x0C: Command("Set_Input_Pos", "目标位置", "fhh", ("Position (rev)", "Velocity FF (0.001 rev/s)", "Torque FF (0.001 Nm)")),
    0x0D: Command("Set_Input_Vel", "目标速度", "ff", ("Velocity (rev/s)", "Torque FF (Nm)")),
    0x0E: Command("Set_Input_Torque", "目标力矩", "f", ("Torque (Nm)",)),
    0x0F: Command("Set_Limits", "速度和电流限制", "ff", ("Velocity limit (rev/s)", "Current limit (A)")),
    0x10: Command("Start_Anticogging", "力矩纹波校准"),
    0x11: Command("Set_Traj_Vel_Limit", "轨迹速度限制", "f", ("Velocity (rev/s)",)),
    0x12: Command("Set_Traj_Accel_Limits", "轨迹加减速度", "ff", ("Acceleration (rev/s²)", "Deceleration (rev/s²)")),
    0x13: Command("Set_Traj_Inertia", "轨迹惯量", "f", ("Inertia (Nm/(rev/s²))",)),
    0x16: Command("Reboot", "重启"),
    0x18: Command("Clear_Errors", "清除故障"),
    0x19: Command("Set_Move_Incremental", "相对位移", "f", ("Rotor displacement (rev)",)),
    0x1A: Command("Set_Pos_Gain", "位置环增益", "f", ("Position Kp",)),
    0x1B: Command("Set_Vel_Gains", "速度环增益", "ff", ("Velocity Kp", "Velocity Ki")),
    0x1E: Command("Disable_Can", "禁用 CAN 并重启"),
    0x1F: Command("Save_Configuration", "保存并重启"),
}

TELEMETRY = {
    0x09: ("Rotor", "ff", ("rev", "rev/s")),
    0x0A: ("Encoder", "ii", ("cnt", "cnt")),
    0x14: ("Iq", "ff", ("A", "A")),
    0x15: ("Temperature", "ff", ("°C", "°C")),
    0x17: ("Bus", "ff", ("V", "A")),
    0x1C: ("Torque", "ff", ("Nm", "Nm")),
    0x1D: ("Power", "ff", ("W", "W")),
}

AXIS_STATES = (0, 1, 3, 4, 7, 8)
CONTROL_MODES = (0, 1, 2, 3)
INPUT_MODES = (0, 1, 2, 3, 5, 6, 9)
ERROR_TYPES = (0, 1, 3, 4)


def simple_id(node: int, command: int) -> int:
    if not 0 <= node <= 63 or not 0 <= command <= 0x1F:
        raise ValueError("Invalid CAN Simple node or command")
    return (node << 5) | command


def frame(can_id: int, data: bytes, transport: int = 0, *, rtr: bool = False) -> CANFrame:
    result = CANFrame(can_id, data, rtr=rtr, fd=transport != 0, brs=transport == 2)
    result.tx_payload()
    return result


def number(value: str, fmt: str) -> int | float:
    value = value.strip()
    if fmt in "fd":
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Expected a finite number")
        return result
    return int(value, 16 if value.lower().lstrip("+-").startswith("0x") else 10)


def command_payload(code: int, values: tuple[str, ...]) -> bytes:
    command = COMMANDS[code]
    if len(values) != len(command.fmt):
        raise ValueError("Invalid number of parameters")
    parsed = tuple(number(value, fmt) for value, fmt in zip(values, command.fmt))
    if code == 0x06:
        simple_id(parsed[0], 0)
    elif code == 0x03 and parsed[0] not in ERROR_TYPES:
        raise ValueError("Invalid error type")
    elif code == 0x07 and parsed[0] not in AXIS_STATES:
        raise ValueError("Invalid axis state")
    elif code == 0x0B and (parsed[0] not in CONTROL_MODES or parsed[1] not in INPUT_MODES):
        raise ValueError("Invalid control or input mode")
    return struct.pack("<" + command.fmt, *parsed).ljust(8, b"\x00")


@dataclass(frozen=True)
class MitLimits:
    position: float = 12.5
    velocity: float = 65.0
    kp: float = 500.0
    kd: float = 5.0
    torque: float = 50.0

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in
               (self.position, self.velocity, self.kp, self.kd, self.torque)):
            raise ValueError("MIT limits must be positive and finite")


def _encode(value: float, low: float, high: float, top: int) -> int:
    if not low <= value <= high:
        raise ValueError("MIT target outside the configured range")
    return int((value - low) * top / (high - low))


def mit_payload(values: tuple[float, float, float, float, float], limits: MitLimits) -> bytes:
    pos, vel, kp, kd, torque = values
    p = _encode(pos, -limits.position, limits.position, 65535)
    v = _encode(vel, -limits.velocity, limits.velocity, 4095)
    k = _encode(kp, 0, limits.kp, 4095)
    d = _encode(kd, 0, limits.kd, 4095)
    t = _encode(torque, -limits.torque, limits.torque, 4095)
    return bytes((p >> 8, p & 0xFF, v >> 4, (v & 0xF) << 4 | k >> 8,
                  k & 0xFF, d >> 4, (d & 0xF) << 4 | t >> 8, t & 0xFF))


def mit_feedback(data: bytes, node: int, limits: MitLimits) -> tuple[float, float, float, int, int] | None:
    if len(data) != 8 or data[0] != node:
        return None
    p = int.from_bytes(data[1:3], "big")
    v = data[3] << 4 | data[4] >> 4
    t = (data[4] & 0xF) << 8 | data[5]
    return (limits.position * (2 * p / 65535 - 1),
            limits.velocity * (2 * v / 4095 - 1),
            limits.torque * (2 * t / 4095 - 1),
            data[6], struct.unpack_from("b", data, 7)[0])


ENDPOINT_FORMATS = {"bool": "?", "int8": "b", "uint8": "B", "int16": "h", "uint16": "H",
                    "int32": "i", "uint32": "I", "float": "f"}
SDO_FORMATS = {2: "b", 3: "h", 4: "i", 5: "B", 6: "H", 7: "I", 8: "f", 1: "?"}


@dataclass(frozen=True)
class Parameter:
    name: str
    index: int
    access: str
    fmt: str
    sub: int = 0
    function: bool = False


def load_endpoints(path: Path) -> list[Parameter]:
    def walk(items, prefix=""):
        for item in items:
            name = prefix + item["name"]
            kind = item["type"]
            if kind == "object":
                yield from walk(item["members"], name + ".")
            elif kind in ENDPOINT_FORMATS:
                yield Parameter(name, item["id"], item["access"], ENDPOINT_FORMATS[kind])
            elif kind == "function":
                yield from walk(item.get("inputs", []), name + ".")
                yield from walk(item.get("outputs", []), name + ".")
                yield Parameter(name, item["id"], "", "", function=True)

    return sorted(walk(json.loads(path.read_text(encoding="utf-8-sig"))), key=lambda item: item.name)


def load_eds(path: Path) -> list[Parameter]:
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.read_string(path.read_text(encoding="utf-8-sig"))
    params = []
    for section in ini.sections():
        match = re.fullmatch(r"([0-9a-f]{4})(?:sub([0-9a-f]+))?", section, re.IGNORECASE)
        if match and ini.has_option(section, "DataType"):
            obj, sub = match.groups()
            fields = ini[section]
            fmt = SDO_FORMATS.get(int(fields["DataType"], 0))
            if fmt:
                access = fields.get("AccessType", "ro").lower()
                params.append(Parameter(fields.get("ParameterName", section), int(obj, 16),
                                        "r" if access == "const" else access, fmt, int(sub or "0", 16)))
    return sorted(params, key=lambda item: (item.index, item.sub))


def parameter_value(param: Parameter, value: str) -> bytes:
    parsed = number(value, param.fmt)
    if param.fmt == "?" and parsed not in (0, 1):
        raise ValueError("Expected 0 or 1")
    return struct.pack("<" + param.fmt, parsed)


def endpoint_payload(endpoint: int, value: bytes | None = None) -> bytes:
    value_bytes = value or b""
    if len(value_bytes) > 4:
        raise ValueError("Endpoint value exceeds 4 bytes")
    return struct.pack("<BHB", int(value is not None), endpoint, 0) + value_bytes.ljust(4, b"\x00")


def sdo_payload(index: int, sub: int, value: bytes | None = None) -> bytes:
    code = 0x40 if value is None else {1: 0x2F, 2: 0x2B, 3: 0x27, 4: 0x23}[len(value)]
    return struct.pack("<BHB", code, index, sub) + (value or b"").ljust(4, b"\x00")
