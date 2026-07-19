"""Trace panel: CAN message stream table (cangaroo style)."""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Tuple, Optional, List

from PySide6.QtCore import (Qt, QAbstractTableModel, QModelIndex, Signal,
                            QTimer)
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (QTableView, QHeaderView, QAbstractItemView,
                                QVBoxLayout, QHBoxLayout, QWidget, QPushButton,
                                QCheckBox, QSpinBox, QLabel)

from canable_sdk import CANFrame
from .i18n import _, language_changed
from .style import id_color, FG_DIM, FG_ACCENT, BG_TX, BG_ERROR


DEFAULT_MAX_ROWS = 30_000


# 预生成 ASCII 转换表：可打印字符保留，其余替换为 '.'
_ASCII_TRANSLATION = bytes.maketrans(
    bytes(range(256)),
    bytes(b if 32 <= b < 127 else ord('.') for b in range(256)),
)


class TraceModel(QAbstractTableModel):
    HEADERS = ["No.", "Time (s)", "Ch", "ID", "Type", "DLC", "Data (hex)", "ASCII",
               "dt (ms)", "Period (ms)", "Count"]

    COL_INDEX, COL_TIME, COL_CH, COL_ID, COL_TYPE, COL_DLC, COL_DATA, \
        COL_ASCII, COL_DELTA, COL_PERIOD, COL_COUNT = range(11)

    def __init__(self, max_rows: int = DEFAULT_MAX_ROWS, parent=None):
        super().__init__(parent)
        self._header_labels = self._make_headers()
        # 完整数据存储：永远不折叠，按时间顺序保留所有帧
        self._rows: Deque[CANFrame] = deque(maxlen=max_rows)
        self._meta: Deque[dict]     = deque(maxlen=max_rows)
        self._text: Deque[list]     = deque(maxlen=max_rows)
        self._counts: Dict[Tuple[int, bool], int] = {}
        self._last_ts: Dict[Tuple[int, bool], float] = {}
        self._period:  Dict[Tuple[int, bool], float] = {}
        self._collapse = False
        # 折叠视图层：仅影响显示，不影响 _rows 存储
        # _view_rows[vis_pos] = _rows 真实索引；每个 cid 只占一个 vis_pos
        self._view_rows: List[int] = []
        self._cid_to_vis: Dict[Tuple[int, bool], int] = {}

    # ---------- Qt model interface ---------- #
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        # 折叠模式下显示行数 = 唯一 cid 数
        return len(self._view_rows) if self._collapse else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._header_labels)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._header_labels[section] if section < len(self._header_labels) else None
        return None

    @staticmethod
    def _format_row(frame: CANFrame, meta: dict) -> list:
        t = frame.timestamp % 1000.0
        ch = "ERR" if frame.is_error else ("TX" if frame.is_tx else "CAN1")
        if frame.is_error:
            cid = "ERROR"
            typ = "ERR"
            dlc = ""
            data = frame._error_info
            ascii = frame._error_info
        else:
            cid = f"{frame.can_id:08X}" if frame.extended else f"{frame.can_id:03X}"
            if frame.rtr:
                typ = "RTR"
            elif frame.fd and frame.brs:
                typ = "FD+BRS"
            elif frame.fd:
                typ = "FD"
            elif frame.extended:
                typ = "Ext"
            else:
                typ = "Std"
            dlc_code = frame.dlc
            data_len = CANFrame.dlc_to_len(dlc_code)
            if dlc_code == data_len:
                dlc = str(dlc_code)
            else:
                dlc = f"{dlc_code} ({data_len})"
            data = frame.data.hex(' ').upper()
            ascii = frame.data.translate(_ASCII_TRANSLATION)
        return [
            "",                         # COL_INDEX — set on insert
            f"{t:12.6f}",
            ch,
            cid,
            typ,
            dlc,
            data,
            ascii,
            f"{meta['dt']:.1f}" if meta['dt'] else "",
            f"{meta['period']:.1f}" if meta['period'] else "",
            str(meta['count']),
        ]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        # 折叠模式：把显示行号映射到 _rows 真实索引
        real_row = self._view_rows[row] if self._collapse else row
        if real_row >= len(self._rows):
            return None
        f = self._rows[real_row]
        col = index.column()

        if role == Qt.DisplayRole and col < len(self._text[real_row]):
            if col == self.COL_INDEX:
                # 折叠模式下也显示真实行号，便于定位
                return f"{real_row + 1}"
            return self._text[real_row][col]

        if role == Qt.BackgroundRole:
            if f.is_error:
                return QBrush(QColor(BG_ERROR))
            if f.is_tx:
                return QBrush(QColor(BG_TX))

        if role == Qt.ForegroundRole:
            if f.is_tx:
                return QBrush(QColor(FG_ACCENT))
            if f.rtr:
                return QBrush(QColor(FG_DIM))
            if not f.is_error:
                return QBrush(QColor(id_color(f.can_id, f.extended)))

        if role == Qt.TextAlignmentRole:
            if col in (self.COL_DLC, self.COL_COUNT):
                return Qt.AlignCenter

        if role == Qt.ToolTipRole:
            return f"ID: 0x{f.can_id:X}  DLC: {f.dlc}\nData: {f.data.hex(' ').upper()}"

        return None

    # ---------- public methods ---------- #
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
        meta = {"dt": dt, "period": period, "count": count}
        txt = self._format_row(frame, meta)

        if self._collapse:
            # 折叠模式：_rows 始终保留所有帧，_view_rows 仅维护显示索引
            will_drop = len(self._rows) == self._rows.maxlen
            if will_drop:
                # popleft 会让 _view_rows 中所有索引失效，整表重建
                self.beginResetModel()
                self._rows.popleft()
                self._meta.popleft()
                self._text.popleft()
                self._rows.append(frame)
                self._meta.append(meta)
                self._text.append(txt)
                self._rebuild_view()
                self.endResetModel()
                return

            new_row_idx = len(self._rows)
            vis_pos = self._cid_to_vis.get(cid)
            if vis_pos is not None:
                # cid 已存在视图：仅更新指向，触发该行重绘
                self._rows.append(frame)
                self._meta.append(meta)
                self._text.append(txt)
                self._view_rows[vis_pos] = new_row_idx
                self.dataChanged.emit(
                    self.index(vis_pos, 0),
                    self.index(vis_pos, self.columnCount() - 1),
                )
            else:
                # 新 cid：在视图末尾追加一行
                vis_pos = len(self._view_rows)
                self._cid_to_vis[cid] = vis_pos
                self.beginInsertRows(QModelIndex(), vis_pos, vis_pos)
                self._rows.append(frame)
                self._meta.append(meta)
                self._text.append(txt)
                self._view_rows.append(new_row_idx)
                self.endInsertRows()
            return

        # 非折叠模式：_rows 索引 == 显示行号
        if len(self._rows) == self._rows.maxlen:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            old = self._rows[0]
            self._rows.popleft()
            self._meta.popleft()
            self._text.popleft()
            old_cid = (old.can_id, old.extended)
            # 若该 ID 已无任何帧，清理统计字典避免无限增长
            if not any((f.can_id, f.extended) == old_cid for f in self._rows):
                self._counts.pop(old_cid, None)
                self._last_ts.pop(old_cid, None)
                self._period.pop(old_cid, None)
            self.endRemoveRows()

        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append(frame)
        self._meta.append(meta)
        self._text.append(txt)
        self.endInsertRows()

    def _rebuild_view(self):
        """从 _rows 重建折叠视图索引。
        - 每个 cid 仅保留最新一次出现的 _rows 索引
        - cid 第一次出现的位置决定其在视图中的顺序（稳定）
        """
        self._view_rows.clear()
        self._cid_to_vis.clear()
        for i, f in enumerate(self._rows):
            cid = (f.can_id, f.extended)
            vis_pos = self._cid_to_vis.get(cid)
            if vis_pos is not None:
                # 已存在：更新指向为更晚的索引
                self._view_rows[vis_pos] = i
            else:
                # 新 cid：追加到视图末尾
                self._cid_to_vis[cid] = len(self._view_rows)
                self._view_rows.append(i)

    def set_collapse_mode(self, on: bool):
        if self._collapse == on:
            return
        self._collapse = on
        self.beginResetModel()
        if on:
            # 进入折叠模式：重建视图索引，但不动 _rows
            self._rebuild_view()
        else:
            # 退出折叠模式：清空视图层，rowCount 直接返回 len(_rows)
            self._view_rows.clear()
            self._cid_to_vis.clear()
        self.endResetModel()

    @staticmethod
    def _make_headers():
        return [_("Trace.No"), _("Trace.Time"), _("Trace.Ch"), _("Trace.ID"), _("Trace.Type"), _("Trace.DLC"), _("Trace.Data"), _("Trace.ASCII"),
                _("Trace.Delta"), _("Trace.Period"), _("Trace.Count")]

    def update_headers(self):
        self._header_labels = self._make_headers()
        self.headerDataChanged.emit(Qt.Horizontal, 0, len(self._header_labels) - 1)

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self._meta.clear()
        self._text.clear()
        self._counts.clear()
        self._last_ts.clear()
        self._period.clear()
        self._view_rows.clear()
        self._cid_to_vis.clear()
        self.endResetModel()

    def id_summary(self):
        result = []
        for cid, count in self._counts.items():
            result.append((cid[0], cid[1], count, self._period.get(cid, 0.0)))
        result.sort(key=lambda x: x[0])
        return result


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
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)

        font = QFont("Consolas", 9)
        font.setFamilies(["Consolas", "Noto Sans Mono CJK SC", "Liberation Mono", "Courier New", "monospace"])
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)

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
            TraceModel.COL_PERIOD:95,
            TraceModel.COL_COUNT: 60,
        }
        for col, w in widths.items():
            h.resizeSection(col, w)
        for c in range(len(TraceModel._make_headers())):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.setSectionResizeMode(TraceModel.COL_DATA, QHeaderView.Stretch)
        h.setSectionResizeMode(TraceModel.COL_COUNT, QHeaderView.Fixed)
        h.setStretchLastSection(False)
        # per-column minimum widths based on header text
        fm = self.fontMetrics()
        self._col_mins = {}
        for c, hdr in enumerate(TraceModel._make_headers()):
            w = fm.horizontalAdvance(hdr) + 14
            self._col_mins[c] = max(w, 30)
        self.horizontalHeader().sectionResized.connect(self._clamp_width)


        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_range)

    def _on_scroll(self, _):
        sb = self.verticalScrollBar()
        self._auto_scroll = (sb.value() >= sb.maximum() - 4)

    def _clamp_width(self, logicalIndex, oldSize, newSize):
        mn = self._col_mins.get(logicalIndex, 30)
        if newSize < mn:
            self.horizontalHeader().resizeSection(logicalIndex, mn)

    def _on_range(self, _min, _max):
        if self._auto_scroll:
            self.verticalScrollBar().setValue(_max)

    def add_frame(self, frame: CANFrame):
        self._model.add_frame(frame)

    def clear(self):
        self._model.clear()

    def set_collapse_mode(self, on: bool):
        self._model.set_collapse_mode(on)

    def id_summary(self):
        return self._model.id_summary()

    def selected_frames(self):
        rows = sorted({i.row() for i in self.selectionModel().selectedIndexes()})
        return [self._model._rows[r] for r in rows if r < len(self._model._rows)]


class TracePanel(QWidget):
    cleared = Signal()
    request_send = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.clear_btn = QPushButton(_("Trace.Clear"))
        self.clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self.clear_btn)

        self.pause_btn = QPushButton(_("Trace.Pause"))
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        bar.addWidget(self.pause_btn)

        self.autoscroll_chk = QCheckBox(_("Trace.AutoScroll"))
        self.autoscroll_chk.setChecked(True)
        self.autoscroll_chk.toggled.connect(self._on_autoscroll)
        bar.addWidget(self.autoscroll_chk)

        self.collapse_chk = QCheckBox(_("Trace.Collapse"))
        self.collapse_chk.setToolTip(_("Trace.CollapseTooltip"))
        
        self.collapse_chk.toggled.connect(self._on_collapse)
        bar.addWidget(self.collapse_chk)


        bar.addStretch()
        layout.addLayout(bar)

        self.view = TraceView(self)
        layout.addWidget(self.view, 1)

        self.summary_label = QLabel(f"{_("Trace.Received")} 0 {_("Trace.Count")}")
        self.summary_label.setStyleSheet(f"color: {FG_DIM};")
        layout.addWidget(self.summary_label)

        self._paused = False
        self._frame_count = 0
        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._update_summary)
        self._summary_timer.start(500)

    def _on_clear(self):
        self.view.clear()
        self._frame_count = 0
        self.summary_label.setText(f"{_('Trace.Received')} 0 {_('Trace.Frames')}")
        self.cleared.emit()

    def _on_pause(self, checked):
        self._paused = checked
        self.pause_btn.setText(_("Trace.Resume") if checked else _("Trace.Pause"))

    def _on_autoscroll(self, checked):
        self.view._auto_scroll = checked
        if checked:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_collapse(self, checked):
        self.view.set_collapse_mode(checked)
        self._update_summary()

    def _update_summary(self):
        n = self._frame_count
        ids = self.view.id_summary()
        uniq = len(ids)
        mode = _("Trace.ModeCollapsed") if self.collapse_chk.isChecked() else _("Trace.ModeAll")
        self.summary_label.setText(
            f"{_("Trace.Received")} {n} {_("Trace.Frames")}   {_("Trace.UniqueIDs")} {uniq}   [{mode}]"
        )

    def append_frame(self, frame: CANFrame):
        if self._paused:
            return
        self.view.add_frame(frame)
        self._frame_count += 1

    def refresh_language(self):
        self.clear_btn.setText(_("Trace.Clear"))
        self.pause_btn.setText(_("Trace.Resume") if self._paused else _("Trace.Pause"))
        self.autoscroll_chk.setText(_("Trace.AutoScroll"))
        self.collapse_chk.setText(_("Trace.Collapse"))
        self._update_summary()
        self.view._model.update_headers()
        hdr = self.view.horizontalHeader()
        hdr.update()
        self.view.update()
        if hasattr(hdr, "headerDataChanged"):
            hdr.headerDataChanged(Qt.Horizontal, 0, self.view._model.columnCount()-1)

    def clear_all(self):
        self._on_clear()
