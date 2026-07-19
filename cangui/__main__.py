"""cangui 命令行入口。

用法：
    python -m cangui
    python cangui.py
"""
import sys
import os
import logging
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont, QFontDatabase

from cangui.main_window import MainWindow
from cangui.style import get_qss

LOGO_PATH = os.path.join(_HERE, "logo.svg")


def _log_dir() -> str:
    """返回日志目录，兼容 PyInstaller 打包环境。"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(_HERE)
    d = os.path.join(base, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def setup_logging():
    """配置根 logger：终端 INFO + 文件 DEBUG，每次启动新文件。

    在 main() 开头调用，确保 python cangui.py 和 python -m cangui 都能触发。
    """
    log_dir = _log_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"canable_{ts}.log")

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler：DEBUG 级别，覆盖所有细节
    file_h = logging.FileHandler(log_path, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt)

    # 终端 handler：INFO 级别，精简输出
    term_h = logging.StreamHandler(sys.stderr)
    term_h.setLevel(logging.INFO)
    term_h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # 清除可能已存在的 handler（避免重复输出）
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_h)
    root.addHandler(term_h)

    # 降低第三方库噪声
    for noisy in ("urllib3", "PIL", "usb._debug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info("日志文件: %s", log_path)
    return log_path


def _pick_app_font() -> QFont:
    """选择系统中可用的最佳中英文字体。

    优先级：SF Pro Display (macOS) → PingFang SC (macOS) →
    Noto Sans CJK SC (Linux) → Microsoft YaHei (Windows) → 系统默认
    """
    available = set(QFontDatabase.families())
    for family in ("SF Pro Display", "SF Pro Text", "PingFang SC",
                   "Noto Sans CJK SC", "Microsoft YaHei", "Noto Sans",
                   "Helvetica Neue", "Segoe UI"):
        if family in available:
            f = QFont(family, 9)
            f.setStyleStrategy(QFont.PreferAntialias)
            return f
    return QFont()


def main():
    # 必须在创建任何业务对象前配置日志
    setup_logging()
    logger = logging.getLogger("cangui.main")
    logger.info("应用启动: python=%s qt=%s", sys.version.split()[0],
                Qt.PYQT_VERSION_STR if hasattr(Qt, 'PYQT_VERSION_STR') else 'PySide6')

    # 让 Ctrl+C 能正常终止程序（Qt 事件循环会吞掉 SIGINT）
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setFont(_pick_app_font())
    app.setOrganizationName("canable")
    app.setApplicationName("CANable2.5")
    app.setWindowIcon(QIcon(LOGO_PATH))
    app.setStyleSheet(get_qss())

    # 定期唤醒 Python 事件循环，确保 SIGINT 能被处理
    from PySide6.QtCore import QTimer
    sigint_timer = QTimer()
    sigint_timer.start(500)
    sigint_timer.timeout.connect(lambda: None)

    win = MainWindow()
    win.setWindowIcon(QIcon(LOGO_PATH))
    win.show()
    exit_code = app.exec()
    logger.info("应用退出: code=%d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
