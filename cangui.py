#!/usr/bin/env python3
"""cangui 启动脚本。直接 python cangui.py 即可运行。

启动时会在终端输出 INFO 级别的日志，包含：
  - CAN 控制器状态（连接 / 启动 / 停止）
  - 每次 TX / RX 帧内容（标准帧 [123 SFF] DE AD BE EF）
  - 错误与警告
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 在 import 任何业务模块前配置 logging，确保 canable_sdk 内的 logger 也能输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

from cangui.__main__ import main
main()
