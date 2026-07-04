"""扫描 CAN FD 数据段波特率。

当对端发送 CAN FD 帧且标称波特率已确认匹配（如 1 Mbps），
但数据段波特率未知时，用此脚本尝试常见组合。

用法:
    python3 scan_fd_data_bitrate.py [nominal_bitrate]
    python3 scan_fd_data_bitrate.py 1000000
"""
from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from zdt_canable import ZDTCanable


def test_fd_configuration(bus: ZDTCanable, nominal: int, data: int, listen_s: float = 4.0) -> int:
    """测试一组 CAN FD 波特率，返回收到的 RX 帧数。"""
    bus.open()
    try:
        bus.set_bitrate(nominal)
        bus.set_data_bitrate(data)
        bus.fd_mode = True
        bus.start(loopback=False)

        print(f"  监听中: nominal={nominal:,}  data={data:,} ...", end="", flush=True)
        rx_count = 0
        err_count = 0
        start = time.time()
        while time.time() - start < listen_s:
            f = bus.receive(timeout=0.1)
            if f is None:
                continue
            if f.is_error:
                err_count += 1
            elif f.is_tx:
                pass
            else:
                rx_count += 1
                print(f"\n    [RX] {f}")

        print(f"  RX={rx_count}  ERR={err_count}")
        return rx_count
    finally:
        try:
            bus.close()
        except Exception:
            pass


def main():
    nominal = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000

    data_rates = [1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000]

    print(f"扫描 CAN FD 标称 {nominal:,} bps 下的数据段波特率...")
    print("请让对端设备持续发送 CAN FD 帧。\n")

    for data in data_rates:
        print(f"[CAN FD data={data:,}]")
        with ZDTCanable() as bus:
            count = test_fd_configuration(bus, nominal, data)
        if count > 0:
            print(f"  *** 收到 CAN FD 数据！匹配配置: nominal={nominal:,} data={data:,} ***\n")
            break
        print()
    else:
        print("未找到匹配的 CAN FD 数据波特率。")
        print("可能原因：")
        print("  - 对端实际发送的是经典 CAN 帧（请用 scan_data_bitrate.py 确认）")
        print("  - 对端使用了非标准数据段采样点")
        print("  - 对端标称波特率不是 1 Mbps")


if __name__ == "__main__":
    main()
