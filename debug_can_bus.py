"""CAN 总线综合调试脚本。

在终端直接运行，不需要 GUI。会依次执行：
1. 回环测试（内部自发自收）
2. 外部总线监听（等待对端发送）
3. 向外部总线发送测试帧并等待 TX echo

用法:
    python3 debug_can_bus.py [bitrate] [data_bitrate]
    python3 debug_can_bus.py 500000
    python3 debug_can_bus.py 1000000 1000000
"""
from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from zdt_canable import ZDTCanable, CANFrame


def section(title: str):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def main():
    bitrate = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    data_bitrate = int(sys.argv[2]) if len(sys.argv) > 2 else None
    fd_mode = data_bitrate is not None

    print(f"测试配置: nominal={bitrate:,} bps  data={data_bitrate}  FD={fd_mode}")

    # ------------------------------------------------------------------ 1. 回环测试
    section("1. 内部回环测试 (loopback mode)")
    with ZDTCanable() as bus:
        bus.open()
        bus.set_bitrate(bitrate)
        if fd_mode:
            bus.set_data_bitrate(data_bitrate)
            bus.fd_mode = True
        bus.start(loopback=True)

        time.sleep(0.05)
        test_frames = [
            CANFrame(can_id=0x100, data=b"\xAA", fd=fd_mode, brs=fd_mode),
            CANFrame(can_id=0x200, data=b"\x11\x22", fd=fd_mode, brs=fd_mode),
            CANFrame(can_id=0x123, data=b"\xDE\xAD\xBE\xEF", fd=fd_mode, brs=fd_mode),
        ]

        loopback_rx = 0
        tx_echo = 0
        deadline = time.time() + 2.0
        for f in test_frames:
            bus.send(f)
            print(f"  TX -> {f}")

        while time.time() < deadline:
            f = bus.receive(timeout=0.1)
            if f is None:
                continue
            if f.is_tx:
                tx_echo += 1
                print(f"  ECHO {f}")
            else:
                loopback_rx += 1
                print(f"  RX   {f}")

        print(f"  发送 {len(test_frames)} 帧，收到回环 {loopback_rx} 帧，TX echo {tx_echo} 个")
        if loopback_rx >= len(test_frames):
            print("  [OK] 回环测试通过，USB 收发路径正常")
        else:
            print("  [FAIL] 回环测试失败，驱动或 USB 通信有问题")

    # ------------------------------------------------------------------ 2. 外部监听
    section("2. 外部总线监听 10 秒（请让对端设备发送数据）")
    with ZDTCanable() as bus:
        bus.open()
        bus.set_bitrate(bitrate)
        if fd_mode:
            bus.set_data_bitrate(data_bitrate)
            bus.fd_mode = True
        bus.start(loopback=False)

        rx_count = 0
        err_count = 0
        start = time.time()
        while time.time() - start < 10.0:
            f = bus.receive(timeout=0.1)
            if f is None:
                continue
            if f.is_error:
                err_count += 1
                print(f"  ERR  {f._error_info}")
            elif f.is_tx:
                print(f"  ECHO {f}")
            else:
                rx_count += 1
                print(f"  RX   {f}")

        print(f"\n  10 秒统计: RX={rx_count}  Error={err_count}")
        if rx_count == 0:
            print("  [WARN] 未收到任何外部 RX 帧。请检查：")
            print("         - 对端设备是否已上电并正在发送")
            print("         - CANH/CANL 是否接反")
            print("         - 总线两端是否有 120Ω 终端电阻")
            print("         - 对端设备波特率/FD 模式是否与本机一致")
        else:
            print(f"  [OK] 收到 {rx_count} 帧外部数据")

    # ------------------------------------------------------------------ 3. 发送测试并等 TX echo
    section("3. 向外部总线发送测试帧并等待 ACK (TX echo)")
    print("  注意：如果总线上只有 CANable 一个节点，将不会收到 TX echo")
    with ZDTCanable() as bus:
        bus.open()
        bus.set_bitrate(bitrate)
        if fd_mode:
            bus.set_data_bitrate(data_bitrate)
            bus.fd_mode = True
        bus.start(loopback=False)

        f = CANFrame(can_id=0x321, data=b"\x01\x02\x03\x04", fd=fd_mode, brs=fd_mode)
        bus.send(f)
        print(f"  TX -> {f}")

        got_echo = False
        deadline = time.time() + 2.0
        while time.time() < deadline:
            r = bus.receive(timeout=0.1)
            if r and r.is_tx:
                got_echo = True
                print(f"  TX echo -> {r}  (说明有对端 ACK)")
                break
            if r and r.is_error:
                print(f"  ERR -> {r._error_info}")

        if not got_echo:
            print("  [WARN] 未收到 TX echo，说明发送的帧没有被任何节点 ACK")


if __name__ == "__main__":
    main()
