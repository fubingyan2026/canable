"""cangui 命令行入口。

用法：
    python -m cangui
    python cangui.py
"""
import sys
import os

# 允许作为脚本直接运行：把父目录加入 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from cangui.main_window import MainWindow
from cangui.style import QSS


def main():
    # 高 DPI 缩放（Qt 6 默认已开启）
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setOrganizationName("canable")
    app.setApplicationName("cangui")
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
