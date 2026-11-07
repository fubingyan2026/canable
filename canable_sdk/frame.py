"""CAN frame data class and DLC helpers.

CANable 2.5 — ElmueSoft protocol frame serialization/deserialization.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Optional

from .constants import (
    CAN_FD_DLC_MAP, DLC_BOUNDARIES,
    MSG_TxFrame, MSG_RxFrame, MSG_TxEcho,
    CAN_ID_Error, CAN_ID_29Bit, CAN_ID_RTR, CAN_MASK_11, CAN_MASK_29,
    ECHO_RxData,
    FRM_FDF, FRM_BRS, FRM_ESI,
    ERID_Bus_is_off, ERID_No_ACK_received, ERID_CRC_Error,
    ERID_Tx_Timeout, ERID_Arbitration_lost,
    ERID_Controller_problem, ERID_Protocol_violation, ERID_Transceiver_error,
    ERID_Bus_error, ERID_Controller_restarted,
)


def _pad_to_dlc(data_len: int) -> int:
    if data_len <= 8:
        return data_len
    for b in DLC_BOUNDARIES:
        if data_len <= b:
            return b
    return 64


# Pre-computed sorted FD DLC entries (dlc > 8 only)
_FD_DLC_SORTED = sorted((dlc, length) for dlc, length in CAN_FD_DLC_MAP.items() if dlc > 8)


def _data_len_to_dlc(data_len: int) -> int:
    if data_len <= 8:
        return data_len
    for dlc, length in _FD_DLC_SORTED:
        if length >= data_len:
            return dlc
    return 15


def _dlc_to_data_len(dlc: int) -> int:
    return CAN_FD_DLC_MAP.get(dlc, 64)


@dataclass
class CANFrame:
    can_id:      int
    data:        bytes = b""
    extended:    bool  = False
    rtr:         bool  = False
    fd:          bool  = False
    brs:         bool  = False
    esi:         bool  = False
    timestamp:   float = 0.0
    echo_id:     int   = 0
    is_tx:       bool  = False
    _error_info: str   = ""

    def __post_init__(self):
        if not isinstance(self.data, bytes):
            self.data = bytes(self.data)

    @property
    def is_error(self) -> bool:
        return bool(self._error_info)

    @property
    def dlc(self) -> int:
        if self.fd:
            return _data_len_to_dlc(len(self.data))
        return min(len(self.data), 8)

    @staticmethod
    def dlc_to_len(dlc: int) -> int:
        return _dlc_to_data_len(dlc)

    def __str__(self) -> str:
        id_fmt = f"{self.can_id:08X}" if self.extended else f"{self.can_id:03X}"
        kind = "EFF" if self.extended else "SFF"
        parts = [kind]
        if self.fd:
            parts.append("FD")
        if self.brs:
            parts.append("BRS")
        if self.esi:
            parts.append("ESI")
        if self.rtr:
            parts.append("RTR")
        data_hex = " ".join(f"{b:02X}" for b in self.data)
        return f"[{id_fmt} {' '.join(parts)}] {data_hex}"

    def __repr__(self) -> str:
        return f"CANFrame({self})"

    def tx_payload(self) -> bytes:
        """Validate a TX frame and return its actual, DLC-aligned wire data."""
        mask = CAN_MASK_29 if self.extended else CAN_MASK_11
        if not isinstance(self.can_id, int) or not 0 <= self.can_id <= mask:
            raise ValueError("CAN ID is outside the selected identifier range")
        if self.is_error:
            raise ValueError("error reports cannot be transmitted as CAN frames")
        if self.fd and self.rtr:
            raise ValueError("CAN FD does not support RTR frames")
        if not self.fd and (self.brs or self.esi):
            raise ValueError("BRS and ESI require CAN FD")
        data = bytes(self.data)
        if len(data) > (64 if self.fd else 8):
            raise ValueError("CAN payload exceeds the frame's maximum length")
        # The firmware rounds the byte count up to a DLC without clearing its
        # reusable USB buffer. Supply every byte that the controller will read.
        return data.ljust(_pad_to_dlc(len(data)), b'\x00') if self.fd else data

    # ----- ElmueSoft TX packing ----- #
    def to_elmue_bytes(self, marker: int = 0) -> bytes:
        raw_data = self.tx_payload()
        if not 0 <= marker <= 255:
            raise ValueError("TX marker must be in 0..255")
        can_id_raw = self.can_id
        if self.extended:
            can_id_raw |= CAN_ID_29Bit
        if self.rtr:
            can_id_raw |= CAN_ID_RTR

        flags = 0
        if self.fd:
            flags |= FRM_FDF
        if self.brs:
            flags |= FRM_BRS
        if self.esi:
            flags |= FRM_ESI

        size = 8 + len(raw_data)
        header = struct.pack('<BB', size, MSG_TxFrame)
        body = struct.pack('<BIB', flags, can_id_raw, marker)
        return header + body + raw_data

    # ----- ElmueSoft RX parsing ----- #
    @classmethod
    def from_elmue_rx(cls, raw: bytes, has_timestamp: bool) -> "CANFrame":
        minimum = 11 if has_timestamp else 7
        if (len(raw) < minimum or raw[0] != len(raw)
                or raw[1] != MSG_RxFrame):
            raise ValueError("invalid ElmueSoft RX message length or header")
        offset = 2
        flags = raw[offset]
        can_id_raw = struct.unpack_from('<I', raw, offset + 1)[0]
        offset += 5

        ts_us = 0
        if has_timestamp:
            ts_us = struct.unpack_from('<I', raw, offset)[0]
            offset += 4

        data = raw[offset:]
        if len(data) > (64 if flags & FRM_FDF else 8):
            raise ValueError("invalid ElmueSoft RX payload length")

        extended = bool(can_id_raw & CAN_ID_29Bit)
        rtr = bool(can_id_raw & CAN_ID_RTR)
        can_id = can_id_raw & CAN_MASK_29 if extended else can_id_raw & CAN_MASK_11
        is_fd = bool(flags & FRM_FDF)
        ts = ts_us / 1_000_000.0 if has_timestamp else time.time()

        return cls(
            can_id=can_id, data=bytes(data), extended=extended, rtr=rtr,
            fd=is_fd, brs=bool(flags & FRM_BRS), esi=bool(flags & FRM_ESI),
            timestamp=ts, is_tx=False,
        )

    # ----- ElmueSoft TX echo parsing ----- #
    @classmethod
    def from_elmue_echo(cls, raw: bytes, has_timestamp: bool,
                        tx_frames: dict = None) -> Optional["CANFrame"]:
        if (len(raw) != (7 if has_timestamp else 3)
                or raw[0] != len(raw) or raw[1] != MSG_TxEcho):
            raise ValueError("invalid ElmueSoft TX echo length or header")
        marker = raw[2]
        ts_us = 0
        if has_timestamp and len(raw) >= 7:
            ts_us = struct.unpack_from('<I', raw, 3)[0]
        ts = ts_us / 1_000_000.0 if has_timestamp else time.time()

        if tx_frames is not None:
            orig = tx_frames.pop(marker, None)
            if orig is None:
                return None
            return cls(
                can_id=orig.can_id, data=orig.data, extended=orig.extended,
                rtr=orig.rtr, fd=orig.fd, brs=orig.brs, esi=orig.esi,
                timestamp=ts, echo_id=marker, is_tx=True,
            )

        return cls(can_id=0, data=b"", timestamp=ts, echo_id=marker, is_tx=True)

    # ----- Legacy parsing ----- #
    @classmethod
    def from_legacy_bytes(cls, raw: bytes, has_timestamp: Optional[bool] = None,
                          fd_mode: Optional[bool] = None) -> Optional["CANFrame"]:
        if len(raw) < 12:
            return None

        echo_id, can_id_full = struct.unpack('<II', raw[:8])
        dlc = raw[8]
        flags = raw[10]

        if dlc > 15:
            return None

        is_fd = bool(flags & FRM_FDF)
        if has_timestamp is None:
            # Compatibility for standalone callers. Drivers must supply the
            # negotiated mode: 76-byte transfers can carry Classic CAN too.
            has_timestamp = len(raw) in (24, 80)
        if fd_mode is None:
            fd_mode = is_fd or len(raw) in (76, 80)
        expected = 12 + (64 if fd_mode else 8) + (4 if has_timestamp else 0)
        if len(raw) != expected or (is_fd and not fd_mode):
            return None
        actual_len = cls.dlc_to_len(dlc) if is_fd else min(dlc, 8)
        data = raw[12:12 + actual_len]

        ts = time.time()
        if has_timestamp:
            ts_us = struct.unpack_from('<I', raw, 76 if is_fd else 20)[0]
            ts = ts_us / 1_000_000.0

        extended = bool(can_id_full & CAN_ID_29Bit)
        rtr = bool(can_id_full & CAN_ID_RTR)
        can_id = can_id_full & CAN_MASK_29 if extended else can_id_full & CAN_MASK_11

        is_error = bool(can_id_full & CAN_ID_Error)
        if is_error:
            parts = []
            if can_id_full & ERID_Tx_Timeout:
                parts.append("TX-TIMEOUT")
            if can_id_full & ERID_Arbitration_lost:
                parts.append("ARB-LOST")
            if can_id_full & ERID_Controller_problem:
                parts.append("CTRL-PROBLEM")
            if can_id_full & ERID_Protocol_violation:
                parts.append("PROTO-VIOLATION")
            if can_id_full & ERID_Transceiver_error:
                parts.append("XCVR-ERR")
            if can_id_full & ERID_No_ACK_received:
                parts.append("NO-ACK")
            if can_id_full & ERID_Bus_is_off:
                parts.append("BUS-OFF")
            if can_id_full & ERID_Bus_error:
                parts.append("BUS-ERR")
            if can_id_full & ERID_Controller_restarted:
                parts.append("CTRL-RESTARTED")
            if can_id_full & ERID_CRC_Error:
                parts.append("CRC-ERR")
            if not parts:
                parts.append(f"ERR-0x{can_id_full & ~CAN_ID_Error:02X}")
            return cls(
                can_id=0, data=bytes([can_id_full & 0xFF]),
                timestamp=time.time(), is_tx=False,
                _error_info=" ".join(parts),
            )

        is_tx = (echo_id != ECHO_RxData)
        return cls(
            can_id=can_id, data=bytes(data), extended=extended, rtr=rtr,
            fd=is_fd, brs=bool(flags & FRM_BRS), esi=bool(flags & FRM_ESI),
            timestamp=ts, echo_id=echo_id if is_tx else 0, is_tx=is_tx,
        )

    # ----- Legacy TX packing ----- #
    def to_legacy_bytes(self) -> bytes:
        raw_data = self.tx_payload()
        can_id_raw = self.can_id
        if self.extended:
            can_id_raw |= CAN_ID_29Bit
        if self.rtr:
            can_id_raw |= CAN_ID_RTR

        flags = 0
        if self.fd:
            flags |= FRM_FDF
        if self.brs:
            flags |= FRM_BRS
        if self.esi:
            flags |= FRM_ESI

        echo_id = self.echo_id if self.echo_id else 1
        dlc = self.dlc

        if self.fd:
            data_padded = raw_data.ljust(64, b'\x00')
            return struct.pack('<IIBBBB64sI',
                               echo_id, can_id_raw, dlc, 0,
                               flags, 0, data_padded, 0)
        else:
            data_padded = raw_data.ljust(8, b'\x00')
            return struct.pack('<IIBBBB8s',
                               echo_id, can_id_raw, dlc, 0,
                               flags, 0, data_padded)
