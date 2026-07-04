"""Send 面板：单帧 / 周期发送（cangaroo 风格）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QAbstractItemView, QDialog, QDialogButtonBox,
                                QFormLayout, QLineEdit, QComboBox, QDoubleSpinBox,
                                QCheckBox, QLabel, QMessageBox)

from canable_sdk import CANFrame
from .style import id_color, FG_DIM


# --------------------------------------------------------------------------- #
#  数据结构
# --------------------------------------------------------------------------- #
@dataclass
class SendEntry:
    can_id:    int   = 0x100
    extended:  bool  = False
    rtr:       bool  = False
    fd:        bool  = False
    brs:       bool  = False
    dlc:       int   = 8
    data:      bytes = b'\x00' * 8
    period_ms: float = 100.0
    enabled:   bool  = True
    sent:      int   = 0
    timer:     Optional[QTimer] = field(default=None, repr=False, compare=False)


# --------------------------------------------------------------------------- #
#  编辑对话框
# --------------------------------------------------------------------------- #
class SendDialog(QDialog):
    # CAN FD DLC 码 → 实际字节数
    FD_DLC_CHOICES = [
        (0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4"),
        (5, "5"), (6, "6"), (7, "7"), (8, "8"),
        (9, "12"), (0xA, "16"), (0xB, "20"), (0xC, "24"),
        (0xD, "32"), (0xE, "48"), (0xF, "64"),
    ]

    def __init__(self, entry: SendEntry, parent=None, fd_mode: bool = False):
        super().__init__(parent)
        self._fd_mode = fd_mode
        self.setWindowTitle("编辑发送报文")
        self.setMinimumWidth(360)
        form = QFormLayout(self)

        self.id_edit = QLineEdit()
        form.addRow("CAN ID (hex):", self.id_edit)

        type_bar = QHBoxLayout()
        self.ext_chk = QCheckBox("扩展帧 (29-bit)")
        self.rtr_chk = QCheckBox("RTR 远程帧")
        self.fd_chk = QCheckBox("CAN FD")
        self.brs_chk = QCheckBox("BRS")
        type_bar.addWidget(self.ext_chk)
        type_bar.addWidget(self.rtr_chk)
        type_bar.addWidget(self.fd_chk)
        type_bar.addWidget(self.brs_chk)
        type_bar.addStretch()
        form.addRow("类型:", type_bar)

        self.dlc_combo = QComboBox()
        for code, label in self.FD_DLC_CHOICES:
            self.dlc_combo.addItem(label, code)
        form.addRow("DLC:", self.dlc_combo)

        self.data_edit = QLineEdit()
        self.data_edit.setPlaceholderText("十六进制，空格分隔，如: DE AD BE EF")
        form.addRow("数据:", self.data_edit)

        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.0, 60000.0)
        self.period_spin.setSuffix(" ms")
        self.period_spin.setDecimals(1)
        self.period_spin.setSingleStep(10.0)
        form.addRow("周期:", self.period_spin)

        self.enable_chk = QCheckBox("启用周期发送")
        form.addRow("", self.enable_chk)

        # 绑定当前值
        self.id_edit.setText(f"{entry.can_id:X}")
        self.ext_chk.setChecked(entry.extended)
        self.rtr_chk.setChecked(entry.rtr)
        self.fd_chk.setChecked(entry.fd)
        self.brs_chk.setChecked(entry.brs)
        # 设置 DLC combo 当前值
        idx = self.dlc_combo.findData(entry.dlc)
        if idx >= 0:
            self.dlc_combo.setCurrentIndex(idx)
        self.data_edit.setText(entry.data.hex(' ').upper())
        self.period_spin.setValue(entry.period_ms)
        self.enable_chk.setChecked(entry.enabled)

        # FD 模式限制
        if not fd_mode:
            self.fd_chk.setChecked(False)
            self.fd_chk.setEnabled(False)
            self.brs_chk.setEnabled(False)
        else:
            # FD 模式下，新帧默认启用 FD + BRS
            if not entry.fd:
                self.fd_chk.setChecked(True)
            if not entry.brs:
                self.brs_chk.setChecked(True)

        # 联动
        self.fd_chk.toggled.connect(self._on_fd_toggled)
        self.dlc_combo.currentIndexChanged.connect(self._truncate_data)
        self._on_fd_toggled(self.fd_chk.isChecked())
        self._truncate_data()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _on_fd_toggled(self, checked: bool):
        self.brs_chk.setEnabled(checked)
        if not checked:
            self.brs_chk.setChecked(False)

    def _truncate_data(self):
        dlc_code = self.dlc_combo.currentData()
        if dlc_code is None:
            return
        actual_len = CANFrame.dlc_to_len(dlc_code) if self.fd_chk.isChecked() else min(dlc_code, 8)
        try:
            raw = bytes.fromhex(self.data_edit.text().replace(' ', ''))
        except ValueError:
            return
        truncated = raw[:actual_len].ljust(actual_len, b'\x00')
        self.data_edit.setText(truncated.hex(' ').upper())

    def get_entry(self, base: Optional[SendEntry] = None) -> SendEntry:
        e = SendEntry() if base is None else base
        try:
            e.can_id = int(self.id_edit.text(), 16)
        except ValueError:
            e.can_id = 0
        e.extended = self.ext_chk.isChecked()
        e.rtr      = self.rtr_chk.isChecked()
        e.fd       = self.fd_chk.isChecked()
        e.brs      = self.brs_chk.isChecked()
        e.dlc      = self.dlc_combo.currentData() or 8
        try:
            data = bytes.fromhex(self.data_edit.text().replace(' ', ''))
            actual_len = CANFrame.dlc_to_len(e.dlc) if e.fd else min(e.dlc, 8)
            e.data = data[:actual_len].ljust(actual_len, b'\x00')
        except ValueError:
            e.data = b'\x00' * (CANFrame.dlc_to_len(e.dlc) if e.fd else min(e.dlc, 8))
        e.period_ms = self.period_spin.value()
        e.enabled   = self.enable_chk.isChecked()
        return e


# --------------------------------------------------------------------------- #
#  面板
# --------------------------------------------------------------------------- #
class SendPanel(QWidget):
    request_send = Signal(object)   # CANFrame
    state_changed = Signal(str)     # 状态文本

    HEADERS = ["#", "ID", "Type", "DLC", "Data", "Period", "Sent", "On"]

    COL_INDEX, COL_ID, COL_TYPE, COL_DLC, COL_DATA, COL_PERIOD, COL_SENT, COL_ON = range(8)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[SendEntry] = []
        self._fd_mode = False
        self._init_ui()
        self._sync_timers()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 表
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(self._on_double_clicked)
        h = self.table.horizontalHeader()
        widths = {self.COL_INDEX: 35, self.COL_ID: 110, self.COL_TYPE: 50,
                  self.COL_DLC: 40, self.COL_DATA: 200, self.COL_PERIOD: 70,
                  self.COL_SENT: 60, self.COL_ON: 35}
        for c, w in widths.items():
            h.resizeSection(c, w)
        h.setSectionResizeMode(self.COL_DATA, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        # 按钮
        bar = QHBoxLayout()
        self.add_btn   = QPushButton("添加")
        self.edit_btn  = QPushButton("编辑")
        self.del_btn   = QPushButton("删除")
        self.send_btn  = QPushButton("发送一次")
        self.start_btn = QPushButton("启动全部")
        self.stop_btn  = QPushButton("停止全部")
        self.clear_btn = QPushButton("清空列表")
        for b in (self.add_btn, self.edit_btn, self.del_btn, self.send_btn,
                  self.start_btn, self.stop_btn, self.clear_btn):
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn.clicked.connect(self._on_delete)
        self.send_btn.clicked.connect(self._on_send_once)
        self.start_btn.clicked.connect(self._on_start_all)
        self.stop_btn.clicked.connect(self._on_stop_all)
        self.clear_btn.clicked.connect(self._on_clear)

        # 状态
        self.status_label = QLabel("已就绪")
        self.status_label.setStyleSheet(f"color: {FG_DIM};")
        layout.addWidget(self.status_label)

    # ---- 内部 ---- #
    def _selected_index(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _refresh_row(self, row: int, e: SendEntry):
        def it(text, align=None, color=None):
            i = QTableWidgetItem(text)
            if align is not None:
                i.setTextAlignment(align)
            if color is not None:
                i.setBackground(QBrush(QColor(color)))
            i.setFlags(i.flags() & ~Qt.ItemIsEditable)
            return i
        align_center = Qt.AlignCenter
        items = [
            it(f"{row+1}",    align_center),
            it(f"{e.can_id:08X}" if e.extended else f"{e.can_id:03X}"),
            it("RTR" if e.rtr else ("FD+BRS" if e.fd and e.brs else ("FD" if e.fd else ("Ext" if e.extended else "Std"))), align_center),
            it(str(e.dlc),    align_center),
            it(e.data.hex(' ').upper()),
            it(f"{e.period_ms:g} ms", align_center),
            it(str(e.sent),   align_center),
            it("✓" if e.enabled else "✗", align_center),
        ]
        for c, item in enumerate(items):
            self.table.setItem(row, c, item)

    def _refresh_all(self):
        self.table.setRowCount(len(self.entries))
        for i, e in enumerate(self.entries):
            self._refresh_row(i, e)

    def _tick(self, e: SendEntry):
        if not e.enabled:
            return
        frame = CANFrame(e.can_id, e.data, extended=e.extended, rtr=e.rtr,
                         fd=e.fd, brs=e.brs)
        self.request_send.emit(frame)
        e.sent += 1
        # 更新计数单元格
        for i, ent in enumerate(self.entries):
            if ent is e:
                self.table.item(i, self.COL_SENT).setText(str(e.sent))
                break

    def _sync_timers(self):
        for e in self.entries:
            if e.timer is None:
                t = QTimer(self)
                t.timeout.connect(lambda ent=e: self._tick(ent))
                e.timer = t
            if e.enabled and e.period_ms > 0:
                if not e.timer.isActive():
                    e.timer.start(max(1, int(e.period_ms)))
            else:
                if e.timer.isActive():
                    e.timer.stop()

    def stop_all_timers(self):
        for e in self.entries:
            if e.timer and e.timer.isActive():
                e.timer.stop()
            e.enabled = False

    # ---- 按钮回调 ---- #
    def _on_add(self):
        dlg = SendDialog(SendEntry(), self, fd_mode=self._fd_mode)
        if dlg.exec() == QDialog.Accepted:
            self.entries.append(dlg.get_entry())
            self._refresh_all()
            self._sync_timers()

    def _on_edit(self):
        idx = self._selected_index()
        if idx is None:
            self.status_label.setText("请先选中一行"); return
        base = self.entries[idx]
        # 暂停 timer 编辑期间不发
        if base.timer and base.timer.isActive():
            base.timer.stop()
        dlg = SendDialog(base, self, fd_mode=self._fd_mode)
        if dlg.exec() == QDialog.Accepted:
            self.entries[idx] = dlg.get_entry(base=base)
            self._refresh_row(idx, self.entries[idx])
        self._sync_timers()

    def _on_delete(self):
        idx = self._selected_index()
        if idx is None:
            self.status_label.setText("请先选中一行"); return
        e = self.entries.pop(idx)
        if e.timer:
            e.timer.stop()
            e.timer.deleteLater()
        self._refresh_all()
        self._sync_timers()

    def _on_send_once(self):
        idx = self._selected_index()
        if idx is None:
            self.status_label.setText("请先选中一行"); return
        e = self.entries[idx]
        frame = CANFrame(e.can_id, e.data, extended=e.extended, rtr=e.rtr,
                         fd=e.fd, brs=e.brs)
        self.request_send.emit(frame)
        e.sent += 1
        self._refresh_row(idx, e)

    def _on_start_all(self):
        for e in self.entries:
            e.enabled = True
        self._sync_timers()
        self._refresh_all()
        self.status_label.setText("已启动全部周期发送")

    def _on_stop_all(self):
        self.stop_all_timers()
        self._refresh_all()
        self.status_label.setText("已停止全部周期发送")

    def _on_clear(self):
        if self.entries and QMessageBox.question(
                self, "清空",
                f"确定要清空 {len(self.entries)} 条发送项？") != QMessageBox.Yes:
            return
        for e in self.entries:
            if e.timer:
                e.timer.stop()
                e.timer.deleteLater()
        self.entries.clear()
        self._refresh_all()
        self.status_label.setText("已清空")

    def _on_double_clicked(self, _index):
        # 双击 = 发送一次
        self._on_send_once()

    # ---- 序列化 ---- #
    def set_fd_mode(self, enabled: bool):
        """切换 FD 模式，影响编辑对话框中的可用选项。"""
        self._fd_mode = enabled

    def to_dict_list(self):
        return [
            {"can_id": e.can_id, "extended": e.extended, "rtr": e.rtr,
             "fd": e.fd, "brs": e.brs,
             "dlc": e.dlc, "data": e.data.hex(), "period_ms": e.period_ms,
             "enabled": e.enabled}
            for e in self.entries
        ]

    def from_dict_list(self, data: list):
        self.entries.clear()
        for d in data:
            e = SendEntry(
                can_id=d["can_id"],
                extended=d.get("extended", False),
                rtr=d.get("rtr", False),
                fd=d.get("fd", False),
                brs=d.get("brs", False),
                dlc=d.get("dlc", 8),
                data=bytes.fromhex(d["data"]),
                period_ms=d.get("period_ms", 100.0),
                enabled=d.get("enabled", True),
            )
            self.entries.append(e)
        self._refresh_all()
        self._sync_timers()
