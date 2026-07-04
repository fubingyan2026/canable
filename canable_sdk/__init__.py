"""CANable 2.5 Python SDK — USB-CAN driver for ElmueSoft firmware.

Quick start:
    from canable_sdk import ZDTCanable, CANFrame

    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()
        frame = bus.receive(timeout=1.0)
"""
from __future__ import annotations

from .driver import ZDTCanable
from .frame import CANFrame
from .constants import logger, CANABLE_VID, CANABLE_PID, FRM_FDF, FRM_BRS, FRM_ESI

__version__ = "0.1.0"

__all__ = [
    "ZDTCanable",
    "CANFrame",
    "logger",
    "CANABLE_VID", "CANABLE_PID",
]
