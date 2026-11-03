"""单通道实时数值波形控件（纯 QPainter，不依赖 QtCharts/QtGraphs）。

设计要点（遵循 cangui 高频渲染规范）：
- 写入 O(1)：样本按 5 ms 时间桶聚合 (min, max, last)，桶队列有上限（25 s）。
- 重绘节流：QTimer 20 FPS，绝不在 add_sample 中触发重绘。
- 三级渲染：桶宽 <1px 按像素列合并 min/max（保尖峰）、<2px 画 min/max 竖线、否则画折线。
- 时间基准用帧时间戳；窗口锚定最新样本，无数据时显示无数据文案。
- 软件零点在绘制时叠加，因此改变零点会即时重居中历史曲线。
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

BUCKET_S = 0.005
MAX_BUCKETS = 5000                  # 25 s @5 ms
RESET_BACK_BUCKETS = int(2.0 / BUCKET_S)
WINDOW_CHOICES = (1.0, 2.0, 5.0, 10.0, 20.0)
DEFAULT_WINDOW_S = 5.0
REPAINT_MS = 50                     # 20 FPS


class ValueScope(QWidget):
    """单通道实时波形：Y 轴自动量程，图例显示当前（含零点）数值。"""

    def __init__(self, name: str, color: str, unit: str = "N", parent=None):
        super().__init__(parent)
        self._name = name
        self._color = QColor(color)
        self._unit = unit
        self._bucket: deque = deque(maxlen=MAX_BUCKETS)
        self._offset = 0.0
        self._window = DEFAULT_WINDOW_S
        self._paused = False
        self._frozen_ref: Optional[float] = None
        self._no_data_text = ""
        self._timer = QTimer(self)
        self._timer.setInterval(REPAINT_MS)
        self._timer.timeout.connect(self.update)
        self.setMinimumHeight(170)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # ── 数据接口（主线程）──
    def add_sample(self, t: Optional[float], raw: float) -> None:
        """写入一个原始值（未加软件零点），t 为帧时间戳（秒）。"""
        if t is None or t <= 0:
            return
        idx = int(t / BUCKET_S)
        d = self._bucket
        if d:
            last_idx = d[-1][0]
            if idx < last_idx - RESET_BACK_BUCKETS:
                d.clear()                      # 时间轴重置（重连/时钟回跳）
            elif idx == last_idx:
                _, lo, hi, _last = d[-1]
                d[-1] = (idx, min(lo, raw), max(hi, raw), raw)
                return
            elif idx < last_idx:
                return                         # 轻微乱序，丢弃
        d.append((idx, raw, raw, raw))

    def set_offset(self, value: float) -> None:
        self._offset = float(value)

    def set_no_data_text(self, text: str) -> None:
        self._no_data_text = text

    def set_window(self, seconds: float) -> None:
        self._window = float(seconds)
        self.update()

    def set_paused(self, paused: bool) -> None:
        if paused and not self._paused:
            self._frozen_ref = self._last_t()
        self._paused = bool(paused)
        self.update()

    def is_paused(self) -> bool:
        return self._paused

    def clear(self) -> None:
        self._bucket.clear()
        self._frozen_ref = None
        self.update()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # ── 内部 ──
    def _last_t(self) -> Optional[float]:
        return self._bucket[-1][0] * BUCKET_S if self._bucket else None

    def _visible(self, t0: float) -> list:
        out = []
        for entry in reversed(self._bucket):
            if entry[0] * BUCKET_S < t0:
                break
            out.append(entry)
        out.reverse()
        return out

    # ── 绘制 ──
    def paintEvent(self, _ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width, height = self.width(), self.height()
        pal = self.palette()
        bg = pal.color(QPalette.ColorRole.Base)
        fg = pal.color(QPalette.ColorRole.WindowText)
        grid = pal.color(QPalette.ColorRole.Mid)
        painter.fillRect(self.rect(), bg)

        left, top, right, bottom = 52, 8, 10, 20
        pw = max(1, width - left - right)
        ph = max(1, height - top - bottom)
        plot = QRectF(left, top, pw, ph)

        if self._paused:
            t_ref = self._frozen_ref
        else:
            t_ref = self._last_t()
            self._frozen_ref = t_ref

        if t_ref is None:
            painter.setPen(QPen(grid, 1))
            painter.drawRect(plot)
            painter.setPen(QPen(fg, 1))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, self._no_data_text)
            return

        t0 = t_ref - self._window
        points = self._visible(t0)
        off = self._offset

        vmin = vmax = None
        for _idx, lo, hi, _last in points:
            lo_v, hi_v = lo + off, hi + off
            vmin = lo_v if vmin is None else min(vmin, lo_v)
            vmax = hi_v if vmax is None else max(vmax, hi_v)
        if vmin is None:
            vmin, vmax = -0.5, 0.5
        pad = (vmax - vmin) * 0.1
        if pad < 1e-9:
            pad = max(0.5, abs(vmax) * 0.1)
        vmin -= pad
        vmax += pad
        span = vmax - vmin

        def y_of(v: float) -> float:
            return top + ph - (v - vmin) / span * ph

        def x_of(t: float) -> float:
            return left + (t - t0) / self._window * pw

        gfont = QFont()
        gfont.setPointSize(max(7, gfont.pointSize() - 1))
        painter.setFont(gfont)
        for i in range(6):
            y = top + ph * i / 5
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(left, y), QPointF(left + pw, y))
            painter.setPen(QPen(fg, 1))
            painter.drawText(QRectF(0, y - 7, left - 5, 14),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "%.3g" % (vmax - span * i / 5))
        for i in range(6):
            x = left + pw * i / 5
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, top), QPointF(x, top + ph))
            painter.setPen(QPen(fg, 1))
            secs = -self._window * (5 - i) / 5
            painter.drawText(QRectF(x - 24, top + ph + 2, 48, bottom - 2),
                             Qt.AlignmentFlag.AlignCenter, "%d s" % int(secs))
        painter.setPen(QPen(grid, 1))
        painter.drawRect(plot)

        bucket_px = pw * BUCKET_S / self._window
        painter.setPen(QPen(self._color, 1.6))
        if bucket_px < 1.0:
            cols: dict = {}
            for entry in points:
                x = int(x_of(entry[0] * BUCKET_S))
                lo, hi = entry[1] + off, entry[2] + off
                cell = cols.get(x)
                if cell is None:
                    cols[x] = [lo, hi]
                else:
                    if lo < cell[0]:
                        cell[0] = lo
                    if hi > cell[1]:
                        cell[1] = hi
            for x, (lo, hi) in cols.items():
                painter.drawLine(QPointF(x + 0.5, y_of(lo)),
                                 QPointF(x + 0.5, y_of(hi)))
        elif bucket_px < 2.0:
            for entry in points:
                x = x_of(entry[0] * BUCKET_S)
                painter.drawLine(QPointF(x, y_of(entry[1] + off)),
                                 QPointF(x, y_of(entry[2] + off)))
        else:
            poly = QPolygonF()
            for entry in points:
                poly.append(QPointF(x_of(entry[0] * BUCKET_S), y_of(entry[3] + off)))
            if poly.size() == 1:
                painter.drawPoint(poly.at(0))
            elif poly.size() > 1:
                painter.drawPolyline(poly)

        # 图例：名称 + 当前（含零点）值
        lfont = QFont()
        lfont.setBold(True)
        painter.setFont(lfont)
        value = points[-1][3] + off if points else None
        label = self._name
        if value is not None:
            label += "  %+.3f %s" % (value, self._unit)
        lx = left + 8
        painter.setPen(QPen(self._color, 2.4))
        painter.drawLine(QPointF(lx, top + 12), QPointF(lx + 18, top + 12))
        painter.setPen(QPen(fg, 1))
        painter.drawText(QPointF(lx + 24, top + 16), label)
