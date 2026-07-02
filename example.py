#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZDT_CANable_2.0pro 使用示例

演示：
    1. 周期性发送 CAN 帧
    2. 阻塞接收单帧
    3. 监听模式（回调 + 线程）
    4. 同时收发（同一台设备做回环测试）
"""

import time
import threading
from zdt_canable import ZDTCanable, CANFrame, logger


# -----------------------------------------------------------------------------
# 示例 1：发送一帧然后退出
# -----------------------------------------------------------------------------
def example_send_one():
    print("\n=== 示例 1：发送一帧 ===")
    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()
        frame = CANFrame(can_id=0x123, data=b'\x01\x02\x03\x04\x05\x06\x07\x08')
        bus.send(frame)
        print(f"已发送: {frame}")


# -----------------------------------------------------------------------------
# 示例 2：周期性发送（模拟电机控制）
# -----------------------------------------------------------------------------
def example_periodic_send():
    print("\n=== 示例 2：周期性发送 0x201 报文 ===")
    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()
        frame = CANFrame(can_id=0x201, data=b'\x00\x10\x00\x00\x00\x00\x00\x00')
        try:
            bus.send_periodic(frame, interval_s=0.05, count=20)
        except KeyboardInterrupt:
            pass
        print("发送完成")


# -----------------------------------------------------------------------------
# 示例 3：接收（超时返回 None）
# -----------------------------------------------------------------------------
def example_receive(timeout_s: float = 5.0):
    print(f"\n=== 示例 3：接收（最多等待 {timeout_s}s）===")
    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()
        print("等待 CAN 帧 ...")
        frame = bus.receive(timeout=timeout_s)
        if frame:
            print(f"收到: {frame}")
        else:
            print("超时，未收到任何帧")


# -----------------------------------------------------------------------------
# 示例 4：监听模式（后台线程 + 回调）
# -----------------------------------------------------------------------------
def example_listen():
    print("\n=== 示例 4：监听模式（按 Ctrl-C 退出）===")

    counter = {"n": 0}

    def on_frame(f: CANFrame):
        counter["n"] += 1
        print(f"[{counter['n']:04d}] RX {f}")

    def on_overflow():
        print("!!! 接收溢出 !!!")

    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()
        bus.on_receive(on_frame)
        bus.on_overflow(on_overflow)
        bus.start_listening()
        print("监听中 ... Ctrl-C 退出")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\n共收到 {counter['n']} 帧")


# -----------------------------------------------------------------------------
# 示例 5：自发自收回环测试（需要把 CANH/CANL 短接或总线只有一台设备）
# -----------------------------------------------------------------------------
def example_loopback():
    print("\n=== 示例 5：自发自收回环测试 ===")
    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()

        received = []

        def cb(f):
            received.append(f)
            print(f"  回环收到: {f}")

        bus.on_receive(cb)
        bus.start_listening()

        test_frames = [
            CANFrame(0x100, b'\xAA'),
            CANFrame(0x200, b'\x11\x22'),
            CANFrame(0x123, b'\xDE\xAD\xBE\xEF'),
            CANFrame(0x7FF, b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'),
        ]

        for f in test_frames:
            bus.send(f)
            print(f"  已发送: {f}")
            time.sleep(0.05)

        # 等待回环帧
        time.sleep(0.5)
        print(f"\n  发送 {len(test_frames)} 帧，收到 {len(received)} 帧")
        if len(received) >= len(test_frames):
            print("  ✓ 回环测试通过")
        else:
            print("  ✗ 未收到全部回环（请检查 CANH/CANL 是否短接）")


# -----------------------------------------------------------------------------
# 示例 6：发送并等待指定 ID 的响应（请求-应答）
# -----------------------------------------------------------------------------
def example_request_response():
    print("\n=== 示例 6：发送请求并等待应答 ===")
    with ZDTCanable() as bus:
        bus.set_bitrate(500_000)
        bus.start()

        # 清空残留
        while bus.receive(timeout=0.05) is not None:
            pass

        req = CANFrame(can_id=0x7DF, data=b'\x02\x01\x0C\x00\x00\x00\x00\x00')  # OBD-II 风格
        bus.send(req)
        print(f"已发送请求: {req}")

        # 等待 ID 0x7E8 的应答，最多 2 秒
        deadline = time.time() + 2.0
        while time.time() < deadline:
            f = bus.receive(timeout=0.1)
            if f and f.can_id == 0x7E8:
                print(f"收到应答: {f}")
                return
        print("超时，未收到 0x7E8 应答")


# -----------------------------------------------------------------------------
def main():
    import sys
    examples = {
        "1": ("发送一帧",            example_send_one),
        "2": ("周期性发送",          example_periodic_send),
        "3": ("接收单帧",            example_receive),
        "4": ("监听模式",            example_listen),
        "5": ("自发自收回环测试",    example_loopback),
        "6": ("请求-应答",           example_request_response),
    }
    if len(sys.argv) > 1 and sys.argv[1] in examples:
        _, fn = examples[sys.argv[1]]
        fn()
        return

    print("ZDT_CANable_2.0pro 示例集合")
    print("=" * 40)
    for k, (name, _) in examples.items():
        print(f"  {k}. {name}")
    print("\n用法: python example.py [1-6]")


if __name__ == "__main__":
    main()
