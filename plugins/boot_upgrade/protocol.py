"""STM32G4 Bootloader 协议编解码。

依据 `boot_protocol_spec.md` V1.3.1 实现：
- 命令字、错误码、ACK/NACK 帧结构
- 各命令帧构造（START / METADATA / DATA / DATA_START / DATA_END / VERIFY / REBOOT / CANCEL）
- 响应帧解析
- 16-bit Block checksum + 32-bit 整包 checksum

纯协议层，无 Qt 依赖，便于单元测试。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

# --------------------------------------------------------------------- #
#  CAN 标识符
# --------------------------------------------------------------------- #
DEFAULT_HOST_ID = 0x701   # Host → Node
DEFAULT_NODE_ID = 0x702    # Node → Host = Host ID + 1


# --------------------------------------------------------------------- #
#  命令字
# --------------------------------------------------------------------- #
class Cmd(IntEnum):
    START      = 0x01   # H→N
    METADATA   = 0x02   # H→N
    DATA       = 0x03   # H→N
    VERIFY     = 0x04   # H→N
    REBOOT     = 0x05   # H→N
    CANCEL     = 0x06   # H→N
    DATA_START = 0x07   # H→N
    DATA_END   = 0x08   # H→N
    ACK        = 0x10   # N→H
    NACK       = 0x11   # N→H


# --------------------------------------------------------------------- #
#  NACK 错误码
# --------------------------------------------------------------------- #
class Err(IntEnum):
    OK                  = 0x00
    BLOCK_CHECKSUM      = 0x01
    FLASH_WRITE_ERR     = 0x02
    FLASH_VERIFY_ERR    = 0x03
    CRC32_ERR           = 0x04
    INVALID_FRAME       = 0x05
    INVALID_STATE       = 0x06
    TIMEOUT             = 0x07
    HW_MISMATCH         = 0x08
    FLASH_ERASE_ERR     = 0x09
    FLASH_READ_ERR      = 0x0A
    FRAME_SIZE          = 0x0B
    FW_TOO_BIG          = 0x0C
    BLOCK_INDEX_MISMATCH = 0x0D


# --------------------------------------------------------------------- #
#  关键常数
# --------------------------------------------------------------------- #
BLOCK_SIZE = 1024                       # 1KB
PROTOCOL_HEADER_LEN = 2                 # Cmd + Seq
SUPPORTED_FRAME_SIZES = (8, 12, 16, 20, 24, 32, 48, 64)

# 节点回这些错误码时在 NACK 负载中带期望块号，Host 据此重同步/断点续传
RESYNC_STATUS = (Err.BLOCK_INDEX_MISMATCH, Err.INVALID_FRAME, Err.TIMEOUT)


# --------------------------------------------------------------------- #
#  响应帧解析
# --------------------------------------------------------------------- #
@dataclass
class AckInfo:
    """ACK/NACK 解析结果。"""
    acked_cmd: int          # 被应答的命令字
    status: int             # 0=成功（ACK）；NACK 时为错误码
    block_index: int        # 仅 DATA_START 应答有效，其余为 0
    is_ack: bool            # True=ACK, False=NACK

    @property
    def ok(self) -> bool:
        return self.is_ack and self.status == Err.OK


def parse_response(frame_data: bytes) -> Optional[AckInfo]:
    """解析 ACK/NACK 帧。

    Args:
        frame_data: 帧的数据部分（取 DLC 范围内）

    Returns:
        AckInfo 或 None（非 ACK/NACK 帧或长度不足）

    注：规范 §4.8 规定 ACK/NACK 固定 8 字节经典 CAN，
        但兼容节点固件可能回 5-7 字节短帧（仍能解析 block_index）。
        长度 < 5 拒绝。
    """
    if len(frame_data) < 5:
        return None
    cmd = frame_data[0]
    if cmd not in (Cmd.ACK, Cmd.NACK):
        return None
    is_ack = cmd == Cmd.ACK
    acked_cmd = frame_data[1]
    status = 0 if is_ack else frame_data[2]
    block_index = (frame_data[3] << 8) | frame_data[4]
    return AckInfo(acked_cmd=acked_cmd, status=status,
                   block_index=block_index, is_ack=is_ack)


def parse_nack_block_index(frame_data: bytes) -> Optional[int]:
    """从 NACK 帧负载提取节点期望的块号（重同步/断点续传）。

    NACK 格式: [0x11][cmd][error_code][idx_H][idx_L][填充]
    返回 Byte 3-4 的 uint16（大端序）；长度不足时返回 None。
    """
    if len(frame_data) < 5:
        return None
    if frame_data[0] != Cmd.NACK:
        return None
    return (frame_data[3] << 8) | frame_data[4]


# --------------------------------------------------------------------- #
#  命令帧构造
# --------------------------------------------------------------------- #
def build_start(fw_size: int, hw_id: int, max_frame_size: int) -> bytes:
    """START 帧 (0x01)，固定 8 字节。"""
    return (bytes([Cmd.START])
            + int(fw_size).to_bytes(4, "big")
            + int(hw_id).to_bytes(2, "big")
            + bytes([max_frame_size]))


def build_metadata(fw_checksum: int, fw_version: int) -> bytes:
    """METADATA 帧 (0x02)，固定 7 字节。"""
    return (bytes([Cmd.METADATA])
            + int(fw_checksum & 0xFFFFFFFF).to_bytes(4, "big")
            + int(fw_version & 0xFFFF).to_bytes(2, "big"))


def build_data_start(block_index: int) -> bytes:
    """DATA_START 帧 (0x07)，固定 8 字节经典 CAN。"""
    return (bytes([Cmd.DATA_START, 0x00])
            + int(block_index & 0xFFFF).to_bytes(2, "big")
            + bytes(4))


def build_data(seq: int, payload: bytes) -> bytes:
    """DATA 帧 (0x03)。"""
    return bytes([Cmd.DATA, seq & 0xFF]) + payload


def build_data_end(seq: int, checksum: int, remaining: bytes) -> bytes:
    """DATA_END 帧 (0x08)。Checksum 固定在 Byte 2-3。"""
    cs_hi = (checksum >> 8) & 0xFF
    cs_lo = checksum & 0xFF
    return bytes([Cmd.DATA_END, seq & 0xFF, cs_hi, cs_lo]) + remaining


def build_verify() -> bytes:
    """VERIFY 帧 (0x04)，2 字节。"""
    return bytes([Cmd.VERIFY, 0x00])


def build_reboot() -> bytes:
    """REBOOT 帧 (0x05)，2 字节。"""
    return bytes([Cmd.REBOOT, 0x00])


def build_cancel() -> bytes:
    """CANCEL 帧 (0x06)，2 字节。"""
    return bytes([Cmd.CANCEL, 0x00])


# --------------------------------------------------------------------- #
#  校验和
# --------------------------------------------------------------------- #
def calc_16bit_checksum(block: bytes) -> int:
    """1KB Block 的 16-bit 累加和（用于 DATA_END）。"""
    s = 0
    for b in block:
        s = (s + b) & 0xFFFF
    return s


def calc_32bit_checksum(fw: bytes) -> int:
    """整包 32-bit 累加和（用于 METADATA / VERIFY）。"""
    s = 0
    for b in fw:
        s = (s + b) & 0xFFFFFFFF
    return s


# --------------------------------------------------------------------- #
#  块切分辅助
# --------------------------------------------------------------------- #
def split_block(block: bytes, max_frame_size: int):
    """将 1KB Block 切分为 (seq, payload) 序列 + DATA_END 尾帧剩余。

    Returns:
        (data_frames, end_seq, end_remaining)
        - data_frames: [(seq, payload), ...]  不含 DATA_END
        - end_seq:     DATA_END 的 Sequence
        - end_remaining: DATA_END 的 Remaining Data（不含 checksum）
    """
    payload_size = max_frame_size - PROTOCOL_HEADER_LEN  # D = N - 2
    if payload_size < 1:
        raise ValueError(f"max_frame_size {max_frame_size} too small")
    if len(block) != BLOCK_SIZE:
        # 零填充到 1024
        block = block + bytes(BLOCK_SIZE - len(block))

    data_frames = []
    offset = 0
    seq = 0
    while offset + payload_size < BLOCK_SIZE:
        data_frames.append((seq, block[offset:offset + payload_size]))
        offset += payload_size
        seq += 1
    # 剩余字节作为 DATA_END 的 Remaining Data
    end_remaining = block[offset:]
    end_seq = seq
    return data_frames, end_seq, end_remaining


def total_blocks(fw_size: int) -> int:
    """根据固件大小计算总块数。"""
    return (fw_size + BLOCK_SIZE - 1) // BLOCK_SIZE
