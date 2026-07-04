"""Trace 面板：CAN 报文流表（cangaroo 风格）。"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Tuple

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, Signal,
                            QTimer)
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (QTableView, QHeaderView, QAbstractItemView,
                                QVBoxLayout, QHBoxLayout, QWidget, QPushButton,
                                QCheckBox, QSpinBox, QLabel)

from canable_sdk import CANFrame
from .style import id_color, FG_DIM


# 最大行数（避免无限增长）
DEFAULT_MAX_ROWS = 50_000


# --------------------------------------------------------------------------- #
#  Model
# --------------------------------------------------------------------------- #
class TraceModel(QAbstractTableModel):
    HEADERS = ["#", "Time (s)", "Ch", "ID", "Type", "DLC", "Data (hex)", "ASCII",
               "Δt (ms)", "Period (ms)", "Count"]

    COL_INDEX, COL_TIME, COL_CH, COL_ID, COL_TYPE, COL_DLC, COL_DATA, \
        COL_ASCII, COL_DELTA, COL_PERIOD, COL_COUNT = range(11)

    def __init__(self, max_rows: int = DEFAULT_MAX_ROWS, parent=None):
        super().__init__(parent)
        self._rows: Deque[CANFrame] = deque(maxlen=max_rows)
        self._meta: Deque[dict]     = deque(maxlen=max_rows)
        self._counts: Dict[Tuple[int, bool], int] = {}
        self._last_ts: Dict[Tuple[int, bool], float] = {}
        self._period:  Dict[Tuple[int, bool], float] = {}

    # ---------- Qt 模型接口 ---------- #
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row >= len(self._rows):
            return None
        f = self._rows[row]
        m = self._meta[row]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == self.COL_INDEX:
                return f"{row + 1}"
            if col == self.COL_TIME:
                t = f.timestamp % 1000.0
                return f"{t:12.6f}"
            if col == self.COL_CH:
                return "ERR" if f.is_error else ("TX" if f.is_tx else "CAN1")
            if col == self.COL_ID:
                if f.is_error:
                    return "ERROR"
                return f"{f.can_id:08X}" if f.extended else f"{f.can_id:03X}"
            if col == self.COL_TYPE:
                if f.is_error:
                    return "ERR"
                if f.rtr:    return "RTR"
                if f.fd and f.brs: return "FD+BRS"
                if f.fd:     return "FD"
                if f.extended: return "Ext"
                return "Std"
            if col == self.COL_DLC:
                return "" if f.is_error else str(f.dlc)
            if col == self.COL_DATA:
                if f.is_error:
                    return f._error_info
                return f.data.hex(' ').upper()
            if col == self.COL_ASCII:
                if f.is_error:
                    return f._error_info
                return ''.join(chr(b) if 32 <= b < 127 else '·' for b in f.data)
            if col == self.COL_DELTA:
                return f"{m['dt']:.1f}" if m['dt'] else ""
            if col == self.COL_PERIOD:
                return f"{m['period']:.1f}" if m['period'] else ""
            if col == self.COL_COUNT:
                return str(m['count'])

        elif role == Qt.BackgroundRole:
            # 错误帧用红色背景
            if f.is_error:
                return QBrush(QColor(140, 40, 40))
            # 本机发送的帧用绿色背景，与接收帧明显区分
            if f.is_tx:
                return QBrush(QColor(50, 110, 60))   # 深绿
            # 按 CAN ID 着色
            color = id_color(f.can_id, f.extended)
            return QBrush(QColor(color))

        elif role == Qt.ForegroundRole:
            # RTR 灰色
            if f.rtr:
                return QBrush(QColor(FG_DIM))

        elif role == Qt.TextAlignmentRole:
            if col in (self.COL_DLC, self.COL_COUNT):
                return Qt.AlignCenter

        elif role == Qt.ToolTipRole:
            return f"ID: 0x{f.can_id:X}  DLC: {f.dlc}\nData: {f.data.hex(' ').upper()}"

        return None

    # ---------- 公开方法 ---------- #
    def add_frame(self, frame: CANFrame):
        cid = (frame.can_id, frame.extended)
        now = frame.timestamp
        self._counts[cid] = self._counts.get(cid, 0) + 1

        dt = 0.0
        if cid in self._last_ts:
            dt = (now - self._last_ts[cid]) * 1000.0
            old = self._period.get(cid, dt)
            self._period[cid] = old * 0.7 + dt * 0.3
        self._last_ts[cid] = now
        period = self._period.get(cid, 0.0)
        count = self._counts[cid]

        if len(self._rows) == self._rows.maxlen:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rows.popleft()
            self._meta.popleft()
            self.endRemoveRows()

        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append(frame)
        self._meta.append({"dt": dt, "period": period, "count": count})
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self._meta.clear()
        self._counts.clear()
        self._last_ts.clear()
        self._period.clear()
        self.endResetModel()

    def id_summary(self):
        """返回 (id, ext, count, period_ms) 列表。"""
        result = []
        for cid, count in self._counts.items():
            result.append((cid[0], cid[1], count, self._period.get(cid, 0.0)))
        result.sort(key=lambda x: x[0])
        return result


# --------------------------------------------------------------------------- #
#  View
# --------------------------------------------------------------------------- #
class TraceView(QTableView):
    def __init__(self, parent=None, max_rows: int = DEFAULT_MAX_ROWS):
        super().__init__(parent)
        self._model = TraceModel(max_rows=max_rows, parent=self)
        self.setModel(self._model)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(18)
        self.setAlternatingRowColors(False)
        self.setSortingEnabled(False)  # 保持插入顺序

        # 字体
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)

        # 自动滚动
        self._auto_scroll = True

        h = self.horizontalHeader()
        h.setHighlightSections(False)
        widths = {
            TraceModel.COL_INDEX:  60,
            TraceModel.COL_TIME:  120,
            TraceModel.COL_CH:    50,
            TraceModel.COL_ID:   110,
            TraceModel.COL_TYPE:  65,
            TraceModel.COL_DLC:   40,
            TraceModel.COL_DATA:  220,
            TraceModel.COL_ASCII: 90,
            TraceModel.COL_DELTA: 70,
            TraceModel.COL_PERIOD:80,
            TraceModel.COL_COUNT: 60,
        }
        for col, w in widths.items():
            h.resizeSection(col, w)
        h.setSectionResizeMode(TraceModel.COL_DATA, QHeaderView.Stretch)
        h.setSectionResizeMode(TraceModel.COL_ASCII, QHeaderView.Stretch)

        # 滚动到底部时禁用自动滚动
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_range)

    def _on_scroll(self, _):
        sb = self.verticalScrollBar()
        self._auto_scroll = (sb.value() >= sb.maximum() - 4)

    def _on_range(self, _min, _max):
        if self._auto_scroll:
            self.verticalScrollBar().setValue(_max)

    # ---- 公开接口 ---- #
    def add_frame(self, frame: CANFrame):
        self._model.add_frame(frame)

    def clear(self):
        self._model.clear()

    def id_summary(self):
        return self._model.id_summary()

    def selected_frames(self):
        rows = sorted({i.row() for i in self.selectionModel().selectedIndexes()})
        return [self._model._rows[r] for r in rows if r < len(self._model._rows)]


# --------------------------------------------------------------------------- #
#  顶部工具栏 + Trace
# --------------------------------------------------------------------------- #
class TracePanel(QWidget):
    """Trace 面板（cangaroo 风格：顶部工具条 + 报文表 + 下方汇总）"""
    cleared = Signal()
    request_send = Signal(object)  # CANFrame （双击时回放）

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 工具条
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self.clear_btn)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        bar.addWidget(self.pause_btn)

        self.autoscroll_chk = QCheckBox("自动滚动")
        self.autoscroll_chk.setChecked(True)
        self.autoscroll_chk.toggled.connect(self._on_autoscroll)
        bar.addWidget(self.autoscroll_chk)

        bar.addWidget(QLabel("最大行数:"))
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1000, 1_000_000)
        self.max_spin.setSingleStep(1000)
        self.max_spin.setValue(DEFAULT_MAX_ROWS)
        bar.addWidget(self.max_spin)

        bar.addStretch()
        layout.addLayout(bar)

        # 表格
        self.view = TraceView(self)
        layout.addWidget(self.view, 1)

        # 汇总
        self.summary_label = QLabel("已接收: 0 帧")
        self.summary_label.setStyleSheet(f"color: {FG_DIM};")
        layout.addWidget(self.summary_label)

        self._paused = False
        self._frame_count = 0
        # 定期刷新汇总
        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._update_summary)
        self._summary_timer.start(500)

    # ---- 回调 ---- #
    def _on_clear(self):
        self.view.clear()
        self._frame_count = 0
        self.summary_label.setText("已接收: 0 帧")
        self.cleared.emit()

    def _on_pause(self, checked):
        self._paused = checked
        self.pause_btn.setText("继续" if checked else "暂停")

    def _on_autoscroll(self, checked):
        self.view._auto_scroll = checked
        if checked:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _update_summary(self):
        n = self._frame_count
        ids = self.view.id_summary()
        uniq = len(ids)
        if not ids:
            self.summary_label.setText(f"已接收: {n} 帧   唯一 ID: 0")
        else:
            self.summary_label.setText(f"已接收: {n} 帧   唯一 ID: {uniq}")

    # ---- 公开接口 ---- #
    def append_frame(self, frame: CANFrame):
        if self._paused:
            return
        self.view.add_frame(frame)
        self._frame_count += 1

    def clear_all(self):
        self._on_clear()
