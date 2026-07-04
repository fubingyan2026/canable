#!/usr/bin/env python3
"""
测试 CAN FD 接收功能
"""
import time
from zdt_canable import ZDTCanable, CANFrame

def test_canfd_receive():
    """测试 CAN FD 接收"""
    print("=== CAN FD 接收测试 ===\n")
    
    # 打开设备
    canable = ZDTCanable()
    canable.open()
    
    # 设置波特率：标称 500k，数据 2M（强制启用 BRS 模式）
    canable.set_bitrate(500_000)
    canable.set_data_bitrate(2_000_000)
    
    # 启动（CAN FD 模式）
    canable.start()
    
    print("已配置：标称 500k，数据 2M（BRS 模式）")
    print("等待接收 CAN FD 帧（10秒）...\n")
    
    # 接收 10 秒
    start_time = time.time()
    rx_count = 0
    classic_count = 0
    fd_count = 0
    
    while time.time() - start_time < 10:
        try:
            frame = canable.receive(timeout=0.1)
            if frame:
                rx_count += 1
                # 检查是否是错误帧
                if hasattr(frame, 'is_error') and frame.is_error:
                    print(f"[ERR] 错误帧: {frame._error_info}")
                elif frame.fd:
                    fd_count += 1
                    print(f"[RX] CAN FD: ID=0x{frame.can_id:03X} Data={frame.data.hex()} BRS={'是' if frame.brs else '否'}")
                else:
                    classic_count += 1
                    print(f"[RX] 经典 CAN: ID=0x{frame.can_id:03X} Data={frame.data.hex()}")
        except Exception as e:
            print(f"接收错误: {e}")
            break
    
    print(f"\n=== 统计 ===")
    print(f"总接收帧数: {rx_count}")
    print(f"  - 经典 CAN: {classic_count}")
    print(f"  - CAN FD: {fd_count}")
    
    canable.close()
    print("\n测试完成")

if __name__ == "__main__":
    test_canfd_receive()
