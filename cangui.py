#!/usr/bin/env python3
"""CANable 2.5 启动脚本。运行 python cangui.py 即可。

日志配置在 cangui/__main__.py 的 setup_logging() 中：
  - 终端输出 INFO 级别（精简，便于实时观察）
  - 文件输出 DEBUG 级别（详细，便于事后排查）
  - 每次启动新建一个日志文件：logs/canable_YYYYMMDD_HHMMSS.log
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cangui.__main__ import main

if __name__ == "__main__":
    main()
