"""Send 面板：单帧 / 周期发送（cangaroo 风格）。"""
from __future__ import annotations

import csv
import os
import sys
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal, QSettings
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                                QTableWidget, QTableWidgetItem, QHeaderView,
                                QAbstractItemView, QDialog, QDialogButtonBox,
                                QFormLayout, QLineEdit, QComboBox, QDoubleSpinBox,
                                QCheckBox, QLabel)

from canable_sdk import CANFrame
from .i18n import _
from .style import id_color, FG_DIM
from . import icons as icon_lib

logger = logging.getLogger("cangui.send")


_SEND_DIR = None

def _csv_dir():
    global _SEND_DIR
    if _SEND_DIR is None:
        if getattr(sys, 'frozen', False):
            _SEND_DIR = os.path.dirname(os.path.abspath(sys.executable))
        else:
            _SEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _SEND_DIR


def _parse_bool(val) -> bool:
    """宽松解析 CSV 中的布尔字段，兼容 True/true/1/yes 等。"""
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "t")


def _dlc_label(dlc_code: int) -> str:
    """DLC 显示：同时展示 DLC 码和实际字节长度（CAN FD 时不同）。"""
    data_len = CANFrame.dlc_to_len(dlc_code)
    if dlc_code == data_len:
        return str(dlc_code)
    return f"{dlc_code} ({data_len})"


# --------------------------------------------------------------------------- #
#  数据结构
# --------------------------------------------------------------------------- #
@dataclass
class SendEntry:
    name:      str   = ""
    can_id:    int   = 0x100
    extended:  bool  = False
    rtr:       bool  = False
    fd:        bool  = False
    brs:       bool  = False
    dlc:       int   = 8
    data:      bytes = b'\x00' * 8
    period_ms: float = 100.0
    enabled:   bool  = False
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
        self.setWindowTitle(_("Send.DialogTitle"))
        self.setMinimumWidth(360)
        form = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(_("Send.NamePlaceholder"))
        form.addRow(_("Send.DlgName"), self.name_edit)

        self.id_edit = QLineEdit()
        form.addRow(_("Send.DlgID"), self.id_edit)

        type_bar = QHBoxLayout()
        self.ext_chk = QCheckBox(_("Send.DlgExt"))
        self.rtr_chk = QCheckBox(_("Send.DlgRTR"))
        self.fd_chk = QCheckBox(_("Send.DlgFD"))
        self.brs_chk = QCheckBox(_("Send.DlgBRS"))
        type_bar.addWidget(self.ext_chk)
        type_bar.addWidget(self.rtr_chk)
        type_bar.addWidget(self.fd_chk)
        type_bar.addWidget(self.brs_chk)
        type_bar.addStretch()
        form.addRow(_("Send.DlgType"), type_bar)

        self.dlc_combo = QComboBox()
        for code, label in self.FD_DLC_CHOICES:
            self.dlc_combo.addItem(label, code)
        form.addRow(_("Send.DlgDLC"), self.dlc_combo)

        self.data_edit = QLineEdit()
        self.data_edit.setPlaceholderText(_("Send.FdDlcHEX"))
        form.addRow(_("Send.DlgData"), self.data_edit)

        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.0, 60000.0)
        self.period_spin.setSuffix(" ms")
        self.period_spin.setDecimals(1)
        self.period_spin.setSingleStep(10.0)
        form.addRow(_("Send.DlgPeriod"), self.period_spin)

        # 绑定当前值
        self.name_edit.setText(entry.name)
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

    def showEvent(self, e):
        super().showEvent(e)
        geo = QSettings("canable", "CANable2.5").value("send_dlg_geo")
        if geo:
            self.restoreGeometry(geo)

    def hideEvent(self, e):
        QSettings("canable", "CANable2.5").setValue("send_dlg_geo", self.saveGeometry())
        super().hideEvent(e)

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
        e.name = self.name_edit.text().strip()
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
        # enabled 由面板底部按钮控制，不在对话框中设置
        if base is None:
            e.enabled = False
        return e


# --------------------------------------------------------------------------- #
#  面板
# --------------------------------------------------------------------------- #
class SendPanel(QWidget):
    request_send = Signal(object)   # CANFrame
    state_changed = Signal(str)     # 状态文本

    @staticmethod
    def HEADERS():
        return [_("Send.HdrName"), _("Send.HdrID"), _("Send.HdrType"), _("Send.HdrDLC"), _("Send.HdrData"), _("Send.HdrPeriod"), _("Send.HdrSent"), _("Send.HdrOn")]

    COL_INDEX, COL_ID, COL_TYPE, COL_DLC, COL_DATA, COL_PERIOD, COL_SENT, COL_ON = range(8)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[SendEntry] = []
        self._fd_mode = False
        self._connected = False  # CAN 设备是否已连接，未连接时禁止启动周期发送
        self._init_ui()
        self._sync_timers()

    def set_connected(self, connected: bool) -> None:
        """由 MainWindow 在连接状态变化时调用。

        未连接时禁止启动周期发送：toggle 按钮仍然可点（用于查看状态），
        但点击启动会被拒绝并提示。已有的 enabled 状态由 ``pause_all_timers``
        / ``resume_timers`` 单独管理，这里只控制"能否新启动"。
        """
        self._connected = connected

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 表
        self.table = QTableWidget(0, len(self.HEADERS()), self)
        self.table.setHorizontalHeaderLabels(self.HEADERS())
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.doubleClicked.connect(self._on_double_clicked)
        h = self.table.horizontalHeader()
        widths = {self.COL_INDEX: 70, self.COL_ID: 110, self.COL_TYPE: 50,
                  self.COL_DLC: 40, self.COL_DATA: 200, self.COL_PERIOD: 70,
                  self.COL_SENT: 60, self.COL_ON: 35}
        for c, w in widths.items():
            h.resizeSection(c, w)
        h.setSectionResizeMode(self.COL_DATA, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        # 按钮（macOS 风格：图标 + 文字）
        # 启停合并为单个 toggle 按钮：根据选中行的 enabled 状态切换文本/图标
        bar = QHBoxLayout()
        self.add_btn   = QPushButton(_("Send.Add"))
        self.add_btn.setIcon(icon_lib.make_icon("plus"))
        self.edit_btn  = QPushButton(_("Send.Edit"))
        self.edit_btn.setIcon(icon_lib.make_icon("pencil"))
        self.del_btn   = QPushButton(_("Send.Delete"))
        self.del_btn.setIcon(icon_lib.make_icon("trash"))
        self.send_btn  = QPushButton(_("Send.SendOnce"))
        self.send_btn.setIcon(icon_lib.make_icon("send"))
        self.toggle_btn = QPushButton(_("Send.Start"))
        self.toggle_btn.setIcon(icon_lib.make_icon("play"))
        self.send_btn.setObjectName("sendBtn")
        self.toggle_btn.setObjectName("toggleBtn")
        for b in (self.add_btn, self.edit_btn, self.del_btn, self.send_btn,
                  self.toggle_btn):
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn.clicked.connect(self._on_delete)
        self.send_btn.clicked.connect(self._on_send_once)
        self.toggle_btn.clicked.connect(self._on_toggle)
        # 选中行变化时同步 toggle 按钮状态
        self.table.currentItemChanged.connect(
            lambda *_: self._update_toggle_btn())

        # 状态
        self.status_label = QLabel(_("Send.Ready"))
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
            it(e.name if e.name else f"#{row+1}", align_center),
            it(f"{e.can_id:08X}" if e.extended else f"{e.can_id:03X}"),
            it("RTR" if e.rtr else ("FD+BRS" if e.fd and e.brs else ("FD" if e.fd else ("Ext" if e.extended else "Std"))), align_center),
            it(_dlc_label(e.dlc), align_center),
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
        """停所有定时器并清空 enabled。用于 to_csv 前 / 退出前彻底停止。"""
        for e in self.entries:
            if e.timer and e.timer.isActive():
                e.timer.stop()
            e.enabled = False
        self._refresh_all()

    def pause_all_timers(self):
        """暂停所有周期发送定时器，但保留 enabled 状态。
        用于 CAN 断开连接场景，重连后可调 resume_timers() 恢复。
        """
        for e in self.entries:
            if e.timer and e.timer.isActive():
                e.timer.stop()
        self._refresh_all()

    def resume_timers(self):
        """根据 enabled 字段恢复所有周期发送定时器。
        用于 CAN 重新连接后自动恢复暂停的发送。
        """
        self._sync_timers()

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
            self.status_label.setText(_("Send.SelectRow")); return
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
            self.status_label.setText(_("Send.SelectRow")); return
        e = self.entries.pop(idx)
        if e.timer:
            e.timer.stop()
            e.timer.deleteLater()
        self._refresh_all()
        self._sync_timers()

    def _on_send_once(self):
        idx = self._selected_index()
        if idx is None:
            self.status_label.setText(_("Send.SelectRow")); return
        e = self.entries[idx]
        frame = CANFrame(e.can_id, e.data, extended=e.extended, rtr=e.rtr,
                         fd=e.fd, brs=e.brs)
        self.request_send.emit(frame)
        e.sent += 1
        self._refresh_row(idx, e)

    def _on_toggle(self):
        """切换选中行的周期发送启停状态。

        合并原 start_btn / stop_btn：根据当前选中行的 ``enabled`` 字段
        自动判断是启动还是停止，并同步按钮文本与图标。

        未连接 CAN 设备时拒绝启动（停止仍允许），避免无效状态切换。
        """
        idx = self._selected_index()
        if idx is None:
            self.status_label.setText(_("Send.SelectRow")); return
        e = self.entries[idx]
        if e.enabled:
            # 当前在运行 → 停止（停止总是允许，即使断开连接）
            logger.info("停止周期发送: idx=%d id=0x%X", idx, e.can_id)
            e.enabled = False
            if e.timer and e.timer.isActive():
                e.timer.stop()
            self._refresh_row(idx, e)
            self.status_label.setText(_("Send.StopAll"))
        else:
            # 当前未运行 → 启动；未连接时拒绝
            if not self._connected:
                logger.debug("启动被拒: 未连接 idx=%d id=0x%X", idx, e.can_id)
                self.status_label.setText(_("Error.NotConnected"))
                return
            e.enabled = True
            self._sync_timers()
            self._refresh_row(idx, e)
            logger.info("启动周期发送: idx=%d id=0x%X period=%dms",
                        idx, e.can_id, e.period_ms)
            self.status_label.setText(_("Send.StartAll"))
        self._update_toggle_btn()

    def _update_toggle_btn(self):
        """根据当前选中行的 enabled 状态更新 toggle 按钮的文本、图标与背景色。

        通过 ``running`` 动态属性切换 QSS 样式：
        - ``running=true``  （运行中）：绿色背景 + 白色文字，提示"点击停止"
        - ``running=false`` （未运行）：默认按钮背景
        """
        idx = self._selected_index()
        running = idx is not None and idx < len(self.entries) and self.entries[idx].enabled
        if running:
            self.toggle_btn.setText(_("Send.Stop"))
            self.toggle_btn.setIcon(icon_lib.make_icon("stop"))
        else:
            self.toggle_btn.setText(_("Send.Start"))
            self.toggle_btn.setIcon(icon_lib.make_icon("play"))
        # 动态属性切换需 unpolish/polish 才能应用新 QSS 规则
        self.toggle_btn.setProperty("running", "true" if running else "false")
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)

    def _on_double_clicked(self, _index):
        # 双击 = 发送一次
        self._on_send_once()

    def refresh_language(self):
        self.add_btn.setText(_("Send.Add"))
        self.edit_btn.setText(_("Send.Edit"))
        self.del_btn.setText(_("Send.Delete"))
        self.send_btn.setText(_("Send.SendOnce"))
        # toggle_btn 文本依赖选中行的 enabled 状态，统一通过 _update_toggle_btn 刷新
        self._update_toggle_btn()
        self.status_label.setText(_("Send.Ready"))
        self.table.setHorizontalHeaderLabels(self.HEADERS())

    def refresh_icons(self):
        """主题切换时重新生成图标。"""
        self.add_btn.setIcon(icon_lib.make_icon("plus"))
        self.edit_btn.setIcon(icon_lib.make_icon("pencil"))
        self.del_btn.setIcon(icon_lib.make_icon("trash"))
        self.send_btn.setIcon(icon_lib.make_icon("send"))
        # toggle_btn 图标随状态变化，统一通过 _update_toggle_btn 刷新
        self._update_toggle_btn()

    # ---- 序列化 ---- #
    def set_fd_mode(self, enabled: bool):
        self._fd_mode = enabled

    def to_dict_list(self):
        return [
            {"name": e.name, "can_id": e.can_id, "extended": e.extended, "rtr": e.rtr,
             "fd": e.fd, "brs": e.brs,
             "dlc": e.dlc, "data": e.data.hex(), "period_ms": e.period_ms,
             "enabled": e.enabled}
            for e in self.entries
        ]

    def from_dict_list(self, data: list):
        self.entries.clear()
        for d in data:
            e = SendEntry(
                name=d.get("name", ""),
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

    CSV_HEADERS = ["name", "can_id", "extended", "rtr", "fd", "brs", "dlc", "data", "period_ms", "enabled"]

    def to_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.CSV_HEADERS)
            for e in self.entries:
                w.writerow([
                    e.name,
                    f"0x{e.can_id:X}", e.extended, e.rtr, e.fd, e.brs,
                    e.dlc, e.data.hex(" ").upper(), e.period_ms, e.enabled,
                ])

    def from_csv(self, path: str):
        self.stop_all_timers()
        self.entries.clear()
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.entries.append(SendEntry(
                    name=row.get("name", ""),
                    can_id=int(row["can_id"], 16),
                    extended=_parse_bool(row["extended"]),
                    rtr=_parse_bool(row["rtr"]),
                    fd=_parse_bool(row["fd"]),
                    brs=_parse_bool(row["brs"]),
                    dlc=int(row["dlc"]),
                    data=bytes.fromhex(row["data"].replace(" ", "")),
                    period_ms=float(row["period_ms"]),
                    enabled=_parse_bool(row["enabled"]),
                ))
            self._refresh_all()
        self._sync_timers()

    @staticmethod
    def csv_path():
        return os.path.join(_csv_dir(), "send_list.csv")

    @staticmethod
    def exists():
        return os.path.exists(SendPanel.csv_path())
