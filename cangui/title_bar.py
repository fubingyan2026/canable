"""macOS 风格自定义标题栏。

特性：
- 左上角红/黄/绿三色交通灯（关闭/最小化/最大化）
- 居中显示窗口标题 "CANable 2.5"
- 鼠标在标题栏任意位置按下可拖动窗口（使用 Qt 的 startSystemMove，跨平台兼容 Wayland）
- 双击标题栏切换最大化/还原
- 鼠标悬停于交通灯组时，所有灯显示内部 glyph（× − +），与原生 macOS 行为一致
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QToolButton,
                                QSizePolicy, QWidget)


class TrafficLight(QToolButton):
    """单个交通灯按钮（红/黄/绿）。

    默认显示纯色圆点；当 ``show_glyph=True`` 时在中央绘制符号（× / − / +），
    还原 macOS "悬停整组才显示 glyph" 的行为。
    """

    # 圆点底色 → glyph 颜色
    _GLYPH_COLORS = {
        "#FF5F57": "#7A0E0E",  # 红 → 深红 ×
        "#FEBC2E": "#7A4F00",  # 黄 → 深棕 −
        "#28C840": "#0A6C1A",  # 绿 → 深绿 +
    }

    def __init__(self, color: str, glyph: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._glyph = glyph
        self._show_glyph = False
        self.setFixedSize(13, 13)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        # 不让 QToolButton 的默认 QSS 影响（我们自绘）
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_show_glyph(self, on: bool) -> None:
        if self._show_glyph != on:
            self._show_glyph = on
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 外圈微弱描边，增强在浅色背景上的可分辨度
        p.setPen(QPen(QColor(0, 0, 0, 35), 0.5))
        p.setBrush(QColor(self._color))
        p.drawEllipse(0.5, 0.5, 12, 12)
        # glyph
        if self._show_glyph:
            p.setPen(QColor(self._GLYPH_COLORS.get(self._color, "#000000")))
            font = QFont()
            font.setPixelSize(9)
            font.setBold(True)
            p.setFont(font)
            p.drawText(self.rect().adjusted(0, -1, 0, 0), Qt.AlignCenter, self._glyph)


class MacTitleBar(QFrame):
    """macOS 风格窗口标题栏。

    用法：
        title_bar = MacTitleBar("CANable 2.5", parent=main_window)
        title_bar.close_requested.connect(main_window.close)
        title_bar.minimize_requested.connect(main_window.showMinimized)
        title_bar.maximize_requested.connect(main_window._toggle_maximize)
    """

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()

    def __init__(self, title: str = "CANable 2.5", parent=None):
        super().__init__(parent)
        self.setObjectName("macTitleBar")
        self.setFixedHeight(38)
        self.setAttribute(Qt.WA_Hover, True)  # 用于 HoverEnter/HoverLeave
        self._title = title

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 0, 13, 0)
        lay.setSpacing(8)

        # 三色交通灯
        self.btn_close = TrafficLight("#FF5F57", "\u00D7")  # ×
        self.btn_min = TrafficLight("#FEBC2E", "\u2212")    # − (U+2212)
        self.btn_max = TrafficLight("#28C840", "+")
        self._lights = (self.btn_close, self.btn_min, self.btn_max)
        for btn in self._lights:
            lay.addWidget(btn)

        # 左侧弹性 + 居中标题 + 右侧弹性
        # 右侧弹性多加一段固定宽度，与左侧交通灯视觉宽度对等，使标题真正居中
        lay.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("macTitleLabel")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 标题对鼠标事件透明，让拖拽在标题文字上也能生效
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.title_label, 2)

        lay.addStretch(1)
        # 右侧占位：与左侧交通灯组宽度对齐（3 灯 + 2 间距 + 左右内边距）
        lay.addSpacing(13 + 3 * 13 + 2 * 8)

        # 信号
        self.btn_close.clicked.connect(self.close_requested.emit)
        self.btn_min.clicked.connect(self.minimize_requested.emit)
        self.btn_max.clicked.connect(self.maximize_requested.emit)

    def set_title(self, title: str) -> None:
        self._title = title
        self.title_label.setText(title)

    # ---- 拖拽移动 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            wh = self.window().windowHandle() if self.window() else None
            if wh is not None:
                # 使用 Qt 提供的系统拖拽：跨平台兼容（X11/Wayland/Windows/macOS）
                wh.startSystemMove()
            e.accept()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.maximize_requested.emit()
            e.accept()
        super().mouseDoubleClickEvent(e)

    # ---- 交通灯组 hover 联动 ----
    def event(self, e):
        t = e.type()
        if t == QEvent.HoverEnter:
            self._set_all_glyphs(True)
        elif t == QEvent.HoverLeave:
            self._set_all_glyphs(False)
        return super().event(e)

    def _set_all_glyphs(self, on: bool) -> None:
        for light in self._lights:
            light.set_show_glyph(on)
