"""USB-CAN device identifiers, protocol constants, and flag enums.

CANable 2.5 — ElmueSoft Candlelight protocol.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("canable_sdk")

# USB identifiers
CANABLE_VID = 0x1D50
CANABLE_PID = 0x606F
EP_IN  = 0x81
EP_OUT = 0x02
MAX_PACKET_SIZE = 64

# --- ElmueSoft message types ---
MSG_TxFrame  = 10
MSG_TxEcho   = 11
MSG_RxFrame  = 12
MSG_Error    = 13
MSG_String   = 14
MSG_Busload  = 15

VALID_MSG_TYPES = {MSG_TxFrame, MSG_TxEcho, MSG_RxFrame, MSG_Error, MSG_String, MSG_Busload}
MAX_ELMUE_MSG_SIZE = 128

# --- Control request codes (eUsbRequest) ---
GS_ReqSetHostFormat     = 0
GS_ReqSetBitTiming      = 1
GS_ReqSetDeviceMode     = 2
# GS_ReqBerrReport      = 3  # not implemented
GS_ReqGetCapabilities   = 4
GS_ReqGetDeviceVersion  = 5
GS_ReqGetTimestamp      = 6
GS_ReqIdentify          = 7
# GS_ReqGetUserID       = 8  # not implemented
# GS_ReqSetUserID       = 9  # not implemented
GS_ReqSetBitTimingFD    = 10
GS_ReqGetCapabilitiesFD = 11
GS_ReqSetTermination    = 12
GS_ReqGetTermination    = 13
# GS_ReqGetState        = 14  # not implemented
ELM_ReqGetBoardInfo     = 20
ELM_ReqSetFilter        = 21
ELM_ReqGetLastError     = 22
ELM_ReqSetBusLoadReport = 23
ELM_ReqSetPinStatus     = 24
ELM_ReqGetPinStatus     = 25

# --- Device flags (eDeviceFlags) ---
GS_DevFlagListenOnly       = 0x0001
GS_DevFlagLoopback         = 0x0002
GS_DevFlagTripleSample     = 0x0004  # not implemented in firmware
GS_DevFlagOneShot          = 0x0008
GS_DevFlagTimestamp        = 0x0010
GS_DevFlagIdentify         = 0x0020
GS_DevFlagUserID           = 0x0040  # not implemented
GS_DevFlagPadPacketsToMaxSize = 0x0080  # not implemented (dangerous)
GS_DevFlagCAN_FD           = 0x0100
GS_DevFlagQuirk_LPC546XX   = 0x0200  # not implemented
GS_DevFlagBitTimingFD      = 0x0400
GS_DevFlagTermination      = 0x0800
GS_DevFlagBerrReporting    = 0x1000  # not implemented
GS_DevFlagGetState         = 0x2000  # not implemented
ELM_DevFlagProtocolElmue   = 0x4000
ELM_DevFlagDisableTxEcho   = 0x8000

# --- CAN ID flags (eCanIdFlags) ---
CAN_ID_Error  = 0x20000000
CAN_ID_RTR    = 0x40000000
CAN_ID_29Bit  = 0x80000000
CAN_MASK_11   = 0x000007FF
CAN_MASK_29   = 0x1FFFFFFF

# --- Frame flags (eFrameFlags) ---
FRM_Overflow = 0x01  # not used
FRM_FDF      = 0x02
FRM_BRS      = 0x04
FRM_ESI      = 0x08

# --- Error flags (eErrFlagsCanID) ---
ERID_Tx_Timeout         = 0x0001
ERID_Arbitration_lost   = 0x0002
ERID_Controller_problem = 0x0004
ERID_Protocol_violation = 0x0008
ERID_Transceiver_error  = 0x0010
ERID_No_ACK_received    = 0x0020
ERID_Bus_is_off         = 0x0040
ERID_Bus_error          = 0x0080
ERID_Controller_restarted = 0x0100
ERID_CRC_Error          = 0x0200

# --- Error app flags (eErrorAppFlags, err_data[5]) ---
APP_CanRxFail      = 0x01
APP_CanTxFail      = 0x02
APP_CanTxOverflow  = 0x04
APP_UsbInOverflow  = 0x08
APP_CanTxTimeout   = 0x10

# --- Error bus status (eErrorBusStatus, err_data[1] high nibble) ---
BUS_StatusActive  = 0x00
BUS_StatusWarning = 0x10
BUS_StatusPassive = 0x20
BUS_StatusOff     = 0x30

# --- Error byte 1 flags (eErrFlagsByte1) ---
ER1_Rx_Errors_at_warning_level = 0x04
ER1_Tx_Errors_at_warning_level = 0x08
ER1_Rx_Passive_status_reached  = 0x10
ER1_Tx_Passive_status_reached  = 0x20
ER1_Bus_is_back_active         = 0x40

# --- Error byte 2 flags (eErrFlagsByte2) - Protocol violation ---
ER2_Single_bit_error             = 0x01
ER2_Frame_format_error           = 0x02
ER2_Bit_stuffing_error           = 0x04
ER2_Unable_to_send_dominant_bit  = 0x08
ER2_Unable_to_send_recessive_bit = 0x10
ER2_Bus_overload                 = 0x20
ER2_Active_error_announcement    = 0x40
ER2_Transmission_error           = 0x80

# --- Error byte 3 flags (eErrFlagsByte3) - Error location ---
ER3_at_ID_bits_28__21    = 0x02
ER3_at_SOF               = 0x03
ER3_at_RTR_substitute    = 0x04
ER3_at_IDE_bit           = 0x05
ER3_at_ID_bits_20__18    = 0x06
ER3_in_data_section      = 0x0A
ER3_at_DLC_bit           = 0x0B
ER3_Intermission         = 0x12
ER3_at_CRC_delimiter     = 0x18
ER3_at_ACK_slot          = 0x19
ER3_at_EOF               = 0x1A

# --- Error byte 4 flags (eErrFlagsByte4) - Transceiver error ---
ER4_CAN_H_No_wire         = 0x04
ER4_CAN_H_Shortcut_to_Bat = 0x05
ER4_CAN_H_Shortcut_to_VCC = 0x06
ER4_CAN_H_Shortcut_to_GND = 0x07
ER4_CAN_H_MASK            = 0x0F
ER4_CAN_L_No_wire         = 0x40
ER4_CAN_L_Shortcut_to_Bat = 0x50
ER4_CAN_L_Shortcut_to_VCC = 0x60
ER4_CAN_L_Shortcut_to_GND = 0x70
ER4_CAN_L_Shortcut_CAN__H = 0x80
ER4_CAN_L_MASK            = 0xF0

# --- Echo ID (eEchoID) - Legacy protocol ---
ECHO_RxData = 0xFFFFFFFF

# --- Device mode (eDeviceMode) ---
GS_ModeReset = 0
GS_ModeStart = 1

# --- Termination (eTermination) ---
GS_TerminationOFF = 0
GS_TerminationON  = 1

# --- Filter operations (eFilterOperation) ---
FIL_ClearAll         = 0
FIL_AcceptMask11bit  = 1
FIL_AcceptMask29bit  = 2

# --- Pin operations (ePinOperation) ---
PINOP_Reset     = 0
PINOP_Set       = 1
PINOP_Tristate  = 2
PINOP_PullDown  = 3
PINOP_PullUp    = 4
PINOP_Disable   = 5
PINOP_Enable    = 6

# --- Pin IDs (ePinID) ---
PINID_BOOT0 = 1

# --- Pin status flags (ePinStatus) ---
PINST_High    = 0x0001
PINST_Enabled = 0x0002

# --- Command feedback codes (eFeedback) ---
FBK_RetString          = 1
FBK_Success            = 2
FBK_InvalidCommand     = 49   # 0x31
FBK_InvalidParameter   = 50
FBK_AdapterMustBeOpen  = 51
FBK_AdapterMustBeClosed = 52
FBK_ErrorFromHAL       = 53
FBK_UnsupportedFeature = 54
FBK_TxBufferFull       = 55
FBK_BusIsOff           = 56
FBK_NoTxInSilentMode   = 57
FBK_BaudrateNotSet     = 58
FBK_OptBytesProgrFailed = 59
FBK_ResetRequired      = 60

# Human-readable feedback descriptions
FEEDBACK_NAMES = {
    FBK_RetString:          "already responded",
    FBK_Success:            "success",
    FBK_InvalidCommand:     "invalid command",
    FBK_InvalidParameter:   "invalid parameter",
    FBK_AdapterMustBeOpen:  "adapter must be open",
    FBK_AdapterMustBeClosed: "adapter must be closed",
    FBK_ErrorFromHAL:       "HAL error",
    FBK_UnsupportedFeature: "unsupported feature",
    FBK_TxBufferFull:       "TX buffer full",
    FBK_BusIsOff:           "bus-off",
    FBK_NoTxInSilentMode:   "no TX in silent mode",
    FBK_BaudrateNotSet:     "baudrate not set",
    FBK_OptBytesProgrFailed: "option bytes programming failed",
    FBK_ResetRequired:      "reset required (reconnect USB)",
}

# --- Misc ---
HOST_FORMAT_MAGIC = 0x0000BEEF
LEGACY_FRAME_SIZE = 80

# --- CAN FD DLC mapping ---
CAN_FD_DLC_MAP = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64,
}

DLC_BOUNDARIES = [8, 12, 16, 20, 24, 32, 48, 64]
