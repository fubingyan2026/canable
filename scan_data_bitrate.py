"""扫描数据波特率，寻找与对端设备匹配的配置。

对端发送 CAN FD 1M 标称波特率的数据，但数据段波特率未知时，
用此脚本自动尝试常见数据波特率。

用法:
    python3 scan_data_bitrate.py [nominal_bitrate]
    python3 scan_data_bitrate.py 1000000
"""
from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from zdt_canable import ZDTCanable


def test_configuration(bus: ZDTCanable, nominal: int, data: int, listen_s: float = 3.0) -> int:
    """测试一组波特率，返回收到的 RX 帧数。"""
    bus.open()
    try:
        bus.set_bitrate(nominal)
        if data:
            bus.set_data_bitrate(data)
            bus.fd_mode = True
        else:
            bus.fd_mode = False
        bus.start(loopback=False)

        print(f"  监听中: nominal={nominal:,}  data={data if data else 'N/A'} ...", end="", flush=True)
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

    # 常见 CAN FD 数据段波特率
    data_rates = [None, 1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000]

    print(f"扫描标称波特率 {nominal:,} bps 下的数据波特率...")
    print("请让对端设备持续发送 CAN FD 帧。\n")

    for data in data_rates:
        label = "经典 CAN (无 data bitrate)" if data is None else f"data={data:,}"
        print(f"[{label}]")
        with ZDTCanable() as bus:
            count = test_configuration(bus, nominal, data)
        if count > 0:
            print(f"  *** 收到数据！匹配配置: nominal={nominal:,} data={data if data else 'N/A'} ***\n")
            break
        print()
    else:
        print("未找到匹配配置。请检查：")
        print("  - 对端是否真的在发送")
        print("  - 物理接线、终端电阻、共地")
        print("  - 对端标称波特率是否也是 1 Mbps")


if __name__ == "__main__":
    main()
