"""ElmueSoft variable-length protocol stream parser."""

import logging
import struct
import time
from typing import Optional

from .constants import (
    MAX_ELMUE_MSG_SIZE, VALID_MSG_TYPES,
    MSG_RxFrame, MSG_TxEcho, MSG_TxFrame, MSG_Error, MSG_String, MSG_Busload,
    CAN_ID_29Bit, CAN_ID_RTR, CAN_MASK_11, CAN_MASK_29,
    FRM_FDF, FRM_BRS, FRM_ESI,
    ERID_Bus_is_off, ERID_No_ACK_received, ERID_CRC_Error,
    ERID_Tx_Timeout, ERID_Arbitration_lost,
    ERID_Controller_problem, ERID_Protocol_violation, ERID_Transceiver_error,
    ERID_Bus_error, ERID_Controller_restarted,
    BUS_StatusOff, BUS_StatusPassive, BUS_StatusWarning, BUS_StatusActive,
    ER1_Bus_is_back_active,
    ER1_Rx_Errors_at_warning_level, ER1_Tx_Errors_at_warning_level,
    ER1_Rx_Passive_status_reached, ER1_Tx_Passive_status_reached,
    ER2_Single_bit_error, ER2_Frame_format_error, ER2_Bit_stuffing_error,
    ER2_Unable_to_send_dominant_bit, ER2_Unable_to_send_recessive_bit,
    ER2_Bus_overload, ER2_Active_error_announcement, ER2_Transmission_error,
    ER3_at_ID_bits_28__21, ER3_at_SOF, ER3_at_RTR_substitute, ER3_at_IDE_bit,
    ER3_at_ID_bits_20__18, ER3_in_data_section, ER3_at_DLC_bit, ER3_Intermission,
    ER3_at_CRC_delimiter, ER3_at_ACK_slot, ER3_at_EOF,
    ER4_CAN_H_No_wire, ER4_CAN_H_Shortcut_to_Bat, ER4_CAN_H_Shortcut_to_VCC,
    ER4_CAN_H_Shortcut_to_GND, ER4_CAN_H_MASK,
    ER4_CAN_L_No_wire, ER4_CAN_L_Shortcut_to_Bat, ER4_CAN_L_Shortcut_to_VCC,
    ER4_CAN_L_Shortcut_to_GND, ER4_CAN_L_Shortcut_CAN__H, ER4_CAN_L_MASK,
    APP_CanTxOverflow, APP_CanTxTimeout, APP_CanRxFail, APP_CanTxFail, APP_UsbInOverflow,
)
from .frame import CANFrame

logger = logging.getLogger("canable_sdk.protocol")

MAX_BUFFER_SIZE = 2048

# 错误帧 Byte3/Byte4 名称表（模块级常量，避免每次解析重建）
_ERR3_LOCATION_NAMES = {
    ER3_at_ID_bits_28__21: "ID28-21",
    ER3_at_SOF: "SOF",
    ER3_at_RTR_substitute: "RTR-sub",
    ER3_at_IDE_bit: "IDE",
    ER3_at_ID_bits_20__18: "ID20-18",
    ER3_in_data_section: "data",
    ER3_at_DLC_bit: "DLC",
    ER3_Intermission: "intermission",
    ER3_at_CRC_delimiter: "CRC-delim",
    ER3_at_ACK_slot: "ACK-slot",
    ER3_at_EOF: "EOF",
}
_ERR4_CAN_H_NAMES = {
    ER4_CAN_H_No_wire: "CAN-H:No wire",
    ER4_CAN_H_Shortcut_to_Bat: "CAN-H:Short→Bat",
    ER4_CAN_H_Shortcut_to_VCC: "CAN-H:Short→VCC",
    ER4_CAN_H_Shortcut_to_GND: "CAN-H:Short→GND",
}
_ERR4_CAN_L_NAMES = {
    ER4_CAN_L_No_wire: "CAN-L:No wire",
    ER4_CAN_L_Shortcut_to_Bat: "CAN-L:Short→Bat",
    ER4_CAN_L_Shortcut_to_VCC: "CAN-L:Short→VCC",
    ER4_CAN_L_Shortcut_to_GND: "CAN-L:Short→GND",
    ER4_CAN_L_Shortcut_CAN__H: "CAN-L:Short→CAN-H",
}


class _ElmueProtocol:
    def __init__(self):
        self._buffer = bytearray()
        self._has_timestamp = False
        self._tx_frames: dict = {}
        self._pending_frames: list = []

    def set_timestamp_mode(self, enabled: bool):
        self._has_timestamp = enabled

    def store_tx_frame(self, marker: int, frame: CANFrame):
        self._tx_frames[marker] = frame

    def clear(self):
        self._buffer.clear()
        self._pending_frames.clear()
        self._tx_frames.clear()

    def feed(self, raw: bytes) -> list:
        self._buffer.extend(raw)
        if len(self._buffer) > MAX_BUFFER_SIZE:
            logger.warning("buffer overflow, discarding %d bytes", len(self._buffer))
            self._buffer.clear()
            return []

        frames = []
        while len(self._buffer) >= 2:
            size = self._buffer[0]
            msg_type = self._buffer[1]

            if size < 2 or size > MAX_ELMUE_MSG_SIZE or msg_type not in VALID_MSG_TYPES:
                self._buffer.pop(0)
                continue

            if len(self._buffer) < size:
                break

            msg = bytes(self._buffer[:size])
            del self._buffer[:size]

            frame = self._parse_message(msg, msg_type)
            if frame is not None:
                frames.append(frame)

        return frames

    def flush_frames(self) -> list:
        frames = self._pending_frames
        self._pending_frames = []
        return frames

    def push_pending(self, frames: list):
        """Prepend frames for next receive call."""
        self._pending_frames = frames + self._pending_frames

    def _parse_message(self, msg: bytes, msg_type: int) -> Optional[CANFrame]:
        logger.debug("parse: type=%d size=%d", msg_type, len(msg))
        if msg_type == MSG_RxFrame:
            return CANFrame.from_elmue_rx(msg, self._has_timestamp)
        elif msg_type == MSG_TxEcho:
            return CANFrame.from_elmue_echo(msg, self._has_timestamp, self._tx_frames)
        elif msg_type == MSG_TxFrame:
            return self._parse_tx_frame(msg)
        elif msg_type == MSG_Error:
            return self._parse_error(msg)
        elif msg_type == MSG_String:
            self._parse_string(msg)
            return None
        elif msg_type == MSG_Busload:
            self._parse_busload(msg)
            return None
        else:
            logger.warning("unknown msg type: %d (size=%d)", msg_type, len(msg))
            return None

    def _parse_tx_frame(self, msg: bytes) -> Optional[CANFrame]:
        if len(msg) < 8:
            return None
        flags = msg[2]
        can_id_raw = struct.unpack_from('<I', msg, 3)[0]
        data = msg[8:]

        extended = bool(can_id_raw & CAN_ID_29Bit)
        rtr = bool(can_id_raw & CAN_ID_RTR)
        can_id = can_id_raw & CAN_MASK_29 if extended else can_id_raw & CAN_MASK_11

        return CANFrame(
            can_id=can_id, data=bytes(data), extended=extended, rtr=rtr,
            fd=bool(flags & FRM_FDF), brs=bool(flags & FRM_BRS),
            esi=bool(flags & FRM_ESI), timestamp=time.time(), is_tx=True,
        )

    def _parse_error(self, msg: bytes) -> CANFrame:
        if len(msg) < 6:
            return CANFrame(can_id=0, _error_info="ERR-SHORT")

        err_id = struct.unpack_from('<I', msg, 2)[0]
        err_data = msg[6:14] if len(msg) >= 14 else b'\x00' * 8

        parts = []

        # --- eErrFlagsCanID ---
        if err_id & ERID_Tx_Timeout:
            parts.append("TX-TIMEOUT")
        if err_id & ERID_Arbitration_lost:
            parts.append("ARB-LOST")
        if err_id & ERID_Controller_problem:
            parts.append("CTRL-PROBLEM")
        if err_id & ERID_Protocol_violation:
            parts.append("PROTO-VIOLATION")
        if err_id & ERID_Transceiver_error:
            parts.append("XCVR-ERR")
        if err_id & ERID_No_ACK_received:
            parts.append("NO-ACK")
        if err_id & ERID_Bus_is_off:
            parts.append("BUS-OFF")
        if err_id & ERID_Bus_error:
            parts.append("BUS-ERR")
        if err_id & ERID_Controller_restarted:
            parts.append("CTRL-RESTARTED")
        if err_id & ERID_CRC_Error:
            parts.append("CRC-ERR")

        # --- Byte 1: Bus status + error level ---
        byte1 = err_data[1] if len(err_data) > 1 else 0
        bus_status = byte1 & 0x30
        if bus_status == BUS_StatusOff:
            parts.append("BUS-OFF")
        elif bus_status == BUS_StatusPassive:
            parts.append("ERROR-PASSIVE")
        elif bus_status == BUS_StatusWarning:
            parts.append("ERROR-WARNING")
        if byte1 & ER1_Rx_Errors_at_warning_level:
            parts.append("RX-WARNING")
        if byte1 & ER1_Tx_Errors_at_warning_level:
            parts.append("TX-WARNING")
        if byte1 & ER1_Rx_Passive_status_reached:
            parts.append("RX-PASSIVE")
        if byte1 & ER1_Tx_Passive_status_reached:
            parts.append("TX-PASSIVE")
        if byte1 & ER1_Bus_is_back_active:
            parts.append("BACK-ACTIVE")

        # --- Byte 2: Protocol violation details ---
        byte2 = err_data[2] if len(err_data) > 2 else 0
        if byte2:
            vio = []
            if byte2 & ER2_Single_bit_error:          vio.append("SINGLE-BIT")
            if byte2 & ER2_Frame_format_error:         vio.append("FRAME-FORMAT")
            if byte2 & ER2_Bit_stuffing_error:         vio.append("BIT-STUFF")
            if byte2 & ER2_Unable_to_send_dominant_bit: vio.append("NO-DOMINANT")
            if byte2 & ER2_Unable_to_send_recessive_bit: vio.append("NO-RECESSIVE")
            if byte2 & ER2_Bus_overload:               vio.append("BUS-OVERLOAD")
            if byte2 & ER2_Active_error_announcement:  vio.append("ACTIVE-ERR")
            if byte2 & ER2_Transmission_error:         vio.append("TX-ERR")
            if vio:
                parts.append("VIOLATION:" + "+".join(vio))

        # --- Byte 3: Protocol violation location ---
        byte3 = err_data[3] if len(err_data) > 3 else 0
        if byte3:
            loc = _ERR3_LOCATION_NAMES.get(byte3)
            if loc:
                parts.append(f"LOC:{loc}")

        # --- Byte 4: Transceiver error ---
        byte4 = err_data[4] if len(err_data) > 4 else 0
        xcvr = []
        hi = byte4 & ER4_CAN_H_MASK
        lo = byte4 & ER4_CAN_L_MASK
        if hi in _ERR4_CAN_H_NAMES:
            xcvr.append(_ERR4_CAN_H_NAMES[hi])
        if lo in _ERR4_CAN_L_NAMES:
            xcvr.append(_ERR4_CAN_L_NAMES[lo])
        if xcvr:
            parts.append("XCVR:" + ", ".join(xcvr))

        # --- Byte 5: App error flags ---
        app_flags = err_data[5] if len(err_data) > 5 else 0
        if app_flags & APP_CanTxOverflow:
            parts.append("TX-OVERFLOW")
        if app_flags & APP_CanTxTimeout:
            parts.append("TX-TIMEOUT")
        if app_flags & APP_CanRxFail:
            parts.append("RX-FAIL")
        if app_flags & APP_CanTxFail:
            parts.append("TX-FAIL")
        if app_flags & APP_UsbInOverflow:
            parts.append("USB-OVERFLOW")

        # --- Byte 6-7: Error counters ---
        tx_err = err_data[6] if len(err_data) > 6 else 0
        rx_err = err_data[7] if len(err_data) > 7 else 0
        if tx_err or rx_err:
            parts.append(f"TEC={tx_err} REC={rx_err}")

        if not parts:
            parts.append(f"ERR-0x{err_id:02X}")

        return CANFrame(
            can_id=0, data=bytes([err_id & 0xFF]),
            timestamp=time.time(), is_tx=False,
            _error_info=" ".join(parts),
        )

    def _parse_string(self, msg: bytes):
        text = msg[2:].decode('ascii', errors='replace')
        text = text.replace('\n', ' ').replace('\r', ' ')
        logger.debug("device: %s", text.strip())

    def _parse_busload(self, msg: bytes):
        if len(msg) >= 3:
            load = msg[2]
            logger.debug("busload: %d%%", load)
