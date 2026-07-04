"""最小化 CAN 接收诊断脚本。

直接读取 USB IN 端点并打印原始十六进制数据，用于判断：
1. 固件是否确实在通过 USB 上报接收到的 CAN 帧
2. 如果没有 USB 数据，说明物理层或对端设备没有发送
"""
from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

from zdt_canable import ZDTCanable, CANFrame


def hex_snip(data: bytes, max_len: int = 64) -> str:
    if len(data) <= max_len:
        return data.hex()
    return data[:max_len].hex() + f"...({len(data)} bytes)"


def main():
    bitrate = 1_000_000
    data_bitrate = 1_000_000
    fd_mode = True

    if len(sys.argv) >= 2:
        bitrate = int(sys.argv[1])
    if len(sys.argv) >= 3:
        data_bitrate = int(sys.argv[2])
        fd_mode = True

    print(f"配置: bitrate={bitrate:,}  data_bitrate={data_bitrate:,}  FD={fd_mode}")
    print("请让对端设备发送 CAN 帧，或运行 example.py 5 做回环测试。\n")

    with ZDTCanable() as bus:
        bus.open()
        bus.set_bitrate(bitrate)
        if fd_mode:
            bus.set_data_bitrate(data_bitrate)
            bus.fd_mode = True
        bus.start()

        # 先发送一帧自测 TX 路径
        test_frame = CANFrame(can_id=0x123, data=b"\xDE\xAD\xBE\xEF", fd=fd_mode, brs=fd_mode)
        bus.send(test_frame)
        print(f"[TX] {test_frame}")

        start = time.time()
        rx_count = 0
        while time.time() - start < 10.0:
            frame = bus.receive(timeout=0.1)
            if frame is not None:
                rx_count += 1
                marker = getattr(frame, "echo_id", None)
                tx_mark = "(TX echo)" if frame.is_tx else "(RX)"
                print(f"[{rx_count}] {tx_mark} {frame}  marker={marker}")

        print(f"\n10 秒内收到 {rx_count} 帧")


if __name__ == "__main__":
    main()
