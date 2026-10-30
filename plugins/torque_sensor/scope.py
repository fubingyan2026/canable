"""双通道扭矩实时波形控件（纯 QPainter 实现，不依赖 QtCharts/QtGraphs）。

设计要点（遵循 cangui 高频渲染规范）：
- **写入 O(1)**：每个样本按 5ms 时间桶聚合 (min, max, last)，桶队列有 maxlen 上限，
  避免存 1000Hz 原始点导致的无界增长。
- **重绘节流**：QTimer ~20Hz 触发 update()，绝不在 add_sample 中触发重绘。
- **绘制解耦**：桶宽 ≥2px 画折线，否则画 min/max 垂直包络，兼顾形状与尖峰。
- **时间基准**：使用帧时间戳（与 UI 无关），窗口锚定最新样本，无数据时冻结。
- 缩放/平移由 time window 控制；Y 轴按可见数据自动缩放并留 10% 边距。
"""
from __future__ import annotations

import time
from collections import deque
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

BUCKET_S = 0.005            # 5ms 时间桶
MAX_BUCKETS = 5000          # 25s @5ms，覆盖最大时间窗
RESET_BACK_BUCKETS = int(2.0 / BUCKET_S)   # 时间轴倒退超过 2s 视为时钟重置
WINDOW_CHOICES = (1.0, 2.0, 5.0, 10.0, 20.0)
DEFAULT_WINDOW_S = 5.0
REPAINT_MS = 50             # 20 FPS


class TorqueScope(QWidget):
    """多通道实时波形控件。每个通道一条曲线，Y 单位 N·m。"""

    def __init__(self, names: List[str], colors: List[str], parent=None):
        super().__init__(parent)
        self._names = list(names)
        self._colors = [QColor(c) for c in colors]
        self._buckets: List[deque] = [deque(maxlen=MAX_BUCKETS) for _ in names]
        self._offsets = [0.0] * len(names)
        self._window = DEFAULT_WINDOW_S
        self._paused = False
        self._frozen_ref: Optional[float] = None
        self._no_data_text = ""
        self._timer = QTimer(self)
        self._timer.setInterval(REPAINT_MS)
        self._timer.timeout.connect(self.update)
        self.setMinimumHeight(160)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # ── 数据接口（主线程）──
    def add_sample(self, ch: int, t: Optional[float], raw: float) -> None:
        """写入一个原始值（未加软件零点），t 为帧时间戳（秒）。"""
        if not (0 <= ch < len(self._buckets)) or t is None or t <= 0:
            return
        idx = int(t / BUCKET_S)
        d = self._buckets[ch]
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

    def set_offset(self, ch: int, value: float) -> None:
        if 0 <= ch < len(self._offsets):
            self._offsets[ch] = float(value)

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
        for d in self._buckets:
            d.clear()
        self._frozen_ref = None
        self.update()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # ── 内部 ──
    def _last_t(self) -> Optional[float]:
        best = None
        for d in self._buckets:
            if d:
                t = d[-1][0] * BUCKET_S
                best = t if best is None else max(best, t)
        return best

    def _visible(self, d: deque, t0: float) -> list:
        """返回 t >= t0 的桶列表（时间有序，反向遍历提前退出）。"""
        out = []
        for entry in reversed(d):
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

        left, top, right, bottom = 48, 8, 10, 20
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
        series = [self._visible(d, t0) for d in self._buckets]

        # Y 自动量程（含软件零点）
        vmin = vmax = None
        for ch, buckets in enumerate(series):
            off = self._offsets[ch]
            for _idx, lo, hi, _last in buckets:
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

        # 网格与坐标
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
                             f"{vmax - span * i / 5:.2f}")
        for i in range(6):
            x = left + pw * i / 5
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, top), QPointF(x, top + ph))
            painter.setPen(QPen(fg, 1))
            secs = -self._window * (5 - i) / 5
            painter.drawText(QRectF(x - 24, top + ph + 2, 48, bottom - 2),
                             Qt.AlignmentFlag.AlignCenter, f"{secs:.0f}s")

        painter.setPen(QPen(grid, 1))
        painter.drawRect(plot)

        # 曲线：先按桶宽选渲染策略，绘制调用数上界约等于像素宽度
        bucket_px = pw * BUCKET_S / self._window
        for ch, buckets in enumerate(series):
            if not buckets:
                continue
            off = self._offsets[ch]
            painter.setPen(QPen(self._colors[ch], 1.6))
            if bucket_px < 1.0:
                # 多个桶映射到同一像素列：按列合并 min/max，保留尖峰
                cols: dict = {}
                for entry in buckets:
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
                for entry in buckets:
                    _idx, lo, hi, _last = entry
                    x = x_of(_idx * BUCKET_S)
                    painter.drawLine(QPointF(x, y_of(lo + off)),
                                     QPointF(x, y_of(hi + off)))
            else:
                poly = QPolygonF()
                for entry in buckets:
                    _idx, _lo, _hi, last = entry
                    poly.append(QPointF(x_of(_idx * BUCKET_S), y_of(last + off)))
                if poly.size() == 1:
                    painter.drawPoint(poly.at(0))
                else:
                    painter.drawPolyline(poly)

        # 图例 + 当前值
        lfont = QFont()
        lfont.setBold(True)
        painter.setFont(lfont)
        metrics = painter.fontMetrics()
        lx = left + 8
        for ch, buckets in enumerate(series):
            painter.setPen(QPen(self._colors[ch], 2.4))
            painter.drawLine(QPointF(lx, top + 12), QPointF(lx + 18, top + 12))
            label = self._names[ch] if ch < len(self._names) else f"ch{ch}"
            if buckets:
                label += f"  {buckets[-1][3] + self._offsets[ch]:+.2f} N·m"
            painter.setPen(QPen(fg, 1))
            painter.drawText(QPointF(lx + 24, top + 16), label)
            lx += 24 + metrics.horizontalAdvance(label) + 20
