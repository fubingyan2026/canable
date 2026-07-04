"""cangui 主窗口（cangaroo 风格布局）。"""
from __future__ import annotations

import csv
import json
from threading import Thread
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, QSettings, QThread, Slot, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QComboBox, QPushButton, QSplitter,
                                QListWidget, QListWidgetItem, QTabWidget,
                                QDockWidget, QStatusBar, QToolBar, QFileDialog,
                                QMessageBox, QInputDialog, QGroupBox, QFormLayout,
                                QDoubleSpinBox, QCheckBox)

from zdt_canable import ZDTCanable, CANFrame
from .style import QSS, FG_ACCENT, FG_DIM, FG_WARN, FG_ERROR
from .worker import CANWorker
from .trace import TracePanel
from .send import SendPanel
from .filters import FilterPanel, StatisticsPanel


# --------------------------------------------------------------------------- #
#  主窗口
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    APP_NAME = "cangui"
    ORG_NAME = "canable"
    WINDOW_TITLE = "cangui — ZDT_CANable 2.0 PRO"

    BITRATES = [10_000, 20_000, 50_000, 100_000, 125_000, 250_000,
                333_000, 500_000, 800_000, 1_000_000]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(1400, 850)

        # 状态
        self._connected = False
        self._worker: Optional[CANWorker] = None
        self._frame_count = 0
        self._last_load = 0.0
        self._last_fps = 0
        self._settings = QSettings(self.ORG_NAME, self.APP_NAME)

        self._build_ui()
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()
        self._wire_signals()

        # 启动时按上次设置恢复
        self._restore_settings()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # 中心：Tab
        self.trace_panel  = TracePanel(self)
        self.stat_panel   = StatisticsPanel(self)
        center_tabs = QTabWidget()
        center_tabs.addTab(self.trace_panel, "Trace")
        center_tabs.addTab(self.stat_panel, "Statistics")
        self._center_tabs = center_tabs

        # 左侧：设备 + 总线
        left = self._build_left_panel()

        # 主分割
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(center_tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 1140])
        self.setCentralWidget(self.splitter)

        # 底部 Send Dock
        self.send_panel = SendPanel(self)
        self.send_dock = QDockWidget("Send Messages", self)
        self.send_dock.setObjectName("SendDock")
        self.send_dock.setWidget(self.send_panel)
        self.send_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.send_dock)

        # 右侧 Filter Dock
        self.filter_panel = FilterPanel(self)
        self.filter_dock = QDockWidget("Filters", self)
        self.filter_dock.setObjectName("FilterDock")
        self.filter_dock.setWidget(self.filter_panel)
        self.filter_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.filter_dock)

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        # 总线配置
        bus_box = QGroupBox("Bus")
        bf = QFormLayout(bus_box)
        self.bitrate_combo = QComboBox()
        for b in self.BITRATES:
            self.bitrate_combo.addItem(f"{b:,} bps", b)
        self.bitrate_combo.setCurrentText("500,000 bps")
        bf.addRow("Bitrate:", self.bitrate_combo)

        # CAN FD 选项
        self.fd_chk = QCheckBox("CAN FD")
        self.fd_chk.toggled.connect(self._on_fd_toggle)
        bf.addRow("", self.fd_chk)

        self.data_bitrate_combo = QComboBox()
        self.data_bitrate_combo.addItem("1,000,000 bps", 1_000_000)
        self.data_bitrate_combo.addItem("2,000,000 bps", 2_000_000)
        self.data_bitrate_combo.addItem("4,000,000 bps", 4_000_000)
        self.data_bitrate_combo.addItem("5,000,000 bps", 5_000_000)
        self.data_bitrate_combo.addItem("8,000,000 bps", 8_000_000)
        self.data_bitrate_combo.setEnabled(False)
        bf.addRow("Data Bitrate:", self.data_bitrate_combo)

        self.sample_combo = QComboBox()
        self.sample_combo.addItems(["87.5% (default)", "75.0%", "66.7%", "50.0%"])
        bf.addRow("Sample Point:", self.sample_combo)
        layout.addWidget(bus_box)

        # 设备
        dev_box = QGroupBox("Devices")
        dv = QVBoxLayout(dev_box)
        self.device_list = QListWidget()
        dv.addWidget(self.device_list)
        scan_btn = QPushButton("扫描设备")
        scan_btn.clicked.connect(self._scan_devices)
        dv.addWidget(scan_btn)
        layout.addWidget(dev_box, 1)

        # 操作
        act_box = QGroupBox("Quick Actions")
        av = QVBoxLayout(act_box)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setCheckable(True)
        self.connect_btn.clicked.connect(self._on_connect_toggle)
        av.addWidget(self.connect_btn)

        identify_btn = QPushButton("LED 闪烁识别")
        identify_btn.clicked.connect(self._on_identify)
        av.addWidget(identify_btn)
        layout.addWidget(act_box)

        return w

    def _build_menubar(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        act_open = QAction("&打开 Trace…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._on_load_trace)
        file_menu.addAction(act_open)
        act_save = QAction("&保存 Trace…", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._on_save_trace)
        file_menu.addAction(act_save)
        file_menu.addSeparator()
        act_save_send = QAction("保存发送列表…", self)
        act_save_send.triggered.connect(self._on_save_send_list)
        file_menu.addAction(act_save_send)
        act_load_send = QAction("加载发送列表…", self)
        act_load_send.triggered.connect(self._on_load_send_list)
        file_menu.addAction(act_load_send)
        file_menu.addSeparator()
        act_quit = QAction("&退出", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # View
        view_menu = mb.addMenu("&View")
        view_menu.addAction(self.send_dock.toggleViewAction())
        view_menu.addAction(self.filter_dock.toggleViewAction())
        act_clear = QAction("清空 Trace", self)
        act_clear.setShortcut("Ctrl+L")
        act_clear.triggered.connect(self.trace_panel.clear_all)
        view_menu.addAction(act_clear)

        # Hardware
        hw_menu = mb.addMenu("&Hardware")
        act_scan = QAction("扫描设备", self)
        act_scan.triggered.connect(self._scan_devices)
        hw_menu.addAction(act_scan)
        act_id = QAction("LED 闪烁", self)
        act_id.triggered.connect(self._on_identify)
        hw_menu.addAction(act_id)
        hw_menu.addSeparator()
        # ElmueSoft 协议 ListenOnly 模式：只听不发，不发送 ACK
        # 注意：想要"自己发自己收"必须接两个 CAN 节点。
        self.act_silent = QAction("Silent 模式 (只听不发)", self)
        self.act_silent.setCheckable(True)
        self.act_silent.toggled.connect(self._on_silent_toggle)
        hw_menu.addAction(self.act_silent)

        # Tools
        tools_menu = mb.addMenu("&Tools")
        act_send_once = QAction("发送单帧…", self)
        act_send_once.setShortcut("Ctrl+Return")
        act_send_once.triggered.connect(self._on_quick_send)
        tools_menu.addAction(act_send_once)

        # Help
        help_menu = mb.addMenu("&Help")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("MainToolBar")
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())
        self.addToolBar(tb)

        # 连接/断开由左侧大按钮控制，工具栏不再重复
        tb.addSeparator()
        tb.addWidget(QLabel("  波特率: "))
        self.tb_bitrate = QComboBox()
        for b in self.BITRATES:
            self.tb_bitrate.addItem(f"{b//1000}k", b)
        self.tb_bitrate.setCurrentIndex(self.BITRATES.index(500_000))
        self.tb_bitrate.currentIndexChanged.connect(self._on_bitrate_changed)
        tb.addWidget(self.tb_bitrate)

        tb.addSeparator()
        self.tb_clear = QAction("清空 Trace", self)
        self.tb_clear.triggered.connect(self.trace_panel.clear_all)
        tb.addAction(self.tb_clear)

        self.tb_pause = QAction("暂停", self)
        self.tb_pause.setCheckable(True)
        self.tb_pause.triggered.connect(lambda v: self.trace_panel._on_pause(v))
        tb.addAction(self.tb_pause)

        tb.addSeparator()
        tb.addAction(self.send_dock.toggleViewAction())
        tb.addAction(self.filter_dock.toggleViewAction())

    def _build_statusbar(self):
        sb: QStatusBar = self.statusBar()
        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("connected", False)
        sb.addWidget(self.status_label)

        sb.addPermanentWidget(QLabel("  "))
        self.bitrate_label = QLabel("— bps")
        sb.addPermanentWidget(self.bitrate_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.fps_label = QLabel("0 fps")
        sb.addPermanentWidget(self.fps_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.load_label = QLabel("负载 0%")
        self.load_label.setObjectName("busLoad")
        sb.addPermanentWidget(self.load_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.count_label = QLabel("总帧数: 0")
        sb.addPermanentWidget(self.count_label)

    # ------------------------------------------------------------ 信号
    def _wire_signals(self):
        # Send → Worker
        self.send_panel.request_send.connect(self._on_send_frame)
        # Filter → Worker
        self.filter_panel.filters_changed.connect(self._on_filters_changed)
        # Bitrate change in side panel
        self.bitrate_combo.currentIndexChanged.connect(self._on_bitrate_combo_changed)

    # ----------------------------------------------------------- 设备扫描
    @Slot()
    def _scan_devices(self):
        self.device_list.clear()
        try:
            devs = ZDTCanable.list_devices()
        except Exception as e:
            QMessageBox.critical(self, "扫描失败", str(e))
            return
        if not devs:
            item = QListWidgetItem("未发现 candleLight 设备")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.device_list.addItem(item)
            return
        for d in devs:
            label = f"{d['manufacturer']} {d['product']}\n  S/N: {d['serial']}"
            li = QListWidgetItem(label)
            li.setData(Qt.UserRole, d)
            self.device_list.addItem(li)
        self.device_list.setCurrentRow(0)

    # ----------------------------------------------------------- CAN FD
    @Slot(bool)
    def _on_fd_toggle(self, enabled: bool):
        self.data_bitrate_combo.setEnabled(enabled)
        # 通知 send 面板更新 DLC 范围
        self.send_panel.set_fd_mode(enabled)

    # ----------------------------------------------------------- 连接
    @Slot()
    def _on_connect_toggle(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if self._worker is not None:
            return
        # 注意：worker 不能有 parent，否则 moveToThread 会被拒绝
        self._worker = CANWorker()
        self._worker.bitrate = self.bitrate_combo.currentData()
        self._worker.fd_mode = self.fd_chk.isChecked()
        if self.fd_chk.isChecked():
            self._worker.data_bitrate = self.data_bitrate_combo.currentData()
        self._worker.frame_received.connect(self._on_frame_received)
        self._worker.state_changed.connect(self._on_state_changed)
        self._worker.error.connect(self._on_error)
        self._worker.bus_stats.connect(self._on_bus_stats)
        # 同步过滤器
        self._worker.set_filters(self.filter_panel.filters)
        # 在独立线程跑 worker 的 connect() + run() 循环
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.connect)
        self._worker_thread.started.connect(self._worker.run)
        # 线程结束时清理 worker
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()
        self._update_connect_ui(True, "正在连接…")

    def _disconnect(self):
        if self._worker is None:
            return
        try:
            self._worker.disconnect()
        except Exception:
            pass
        # 终止线程
        if hasattr(self, "_worker_thread") and self._worker_thread is not None:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
        # worker 和 thread 由 finished 信号统一 deleteLater，
        # 这里仅释放 Python 引用，避免重复 delete 导致 libshiboken 报错
        self._worker = None
        self._update_connect_ui(False, "已断开")

    def _update_connect_ui(self, connected: bool, msg: str):
        self._connected = connected
        self.status_label.setText(msg)
        self.status_label.setProperty("connected", connected)
        # 重新应用属性样式
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.connect_btn.setChecked(connected)
        self.connect_btn.setText("断开" if connected else "连接")
        self.bitrate_combo.setEnabled(not connected)
        self.tb_bitrate.setEnabled(not connected)
        self.bitrate_label.setText(f"{self.bitrate_combo.currentData():,} bps" if connected else "— bps")

    @Slot()
    def _on_identify(self):
        """让设备 LED 闪烁一下，便于多台设备时定位。"""
        def _run():
            try:
                if self._worker is not None and self._worker._bus is not None:
                    self._worker._bus.identify(1500)
                else:
                    with ZDTCanable() as b:
                        b.identify(1500)
                self.status_label.setText("设备 LED 闪烁中…")
            except Exception as e:
                QMessageBox.warning(self, "LED 识别", f"失败: {e}")

        Thread(target=_run, daemon=True).start()

    @Slot(bool)
    def _on_silent_toggle(self, enabled: bool):
        """Silent 模式开关 (M0/M1)。

        M1: 只听不发 (listen-only, TX 帧被硬件拒绝，word_led 不会闪)
        M0: Normal (TX 帧发到物理总线)

        注意：canable2 固件没有 loopback；silent 模式**不能**用来测试 TX。
        """
        def _run():
            try:
                if self._worker is not None and self._worker._bus is not None:
                    self._worker._bus.set_silent(enabled)
                else:
                    with ZDTCanable() as b:
                        b.set_silent(enabled)
                mode = "Silent (只听不发)" if enabled else "Normal (发到总线)"
                self.status_label.setText(f"canable2 模式: {mode}")
            except Exception as e:
                QMessageBox.warning(self, "Silent 模式", f"失败: {e}")
                self.act_silent.blockSignals(True)
                self.act_silent.setChecked(not enabled)
                self.act_silent.blockSignals(False)

        Thread(target=_run, daemon=True).start()

    @Slot(bool, str)
    def _on_state_changed(self, connected: bool, msg: str):
        if connected:
            self._update_connect_ui(True, msg)
        else:
            self._update_connect_ui(False, msg)

    @Slot(str)
    def _on_error(self, err: str):
        self.status_label.setText(err)
        self.status_label.setProperty("connected", False)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.count_label.setText(f"⚠ {err[:60]}")

    @Slot(object)
    def _on_frame_received(self, frame: CANFrame):
        self._frame_count += 1
        self.trace_panel.append_frame(frame)

    @Slot(float, int)
    def _on_bus_stats(self, load: float, fps: int):
        self._last_load = load
        self._last_fps = fps
        self.fps_label.setText(f"{fps} fps")
        self.load_label.setText(f"负载 {load:.1f}%")
        if load < 40:
            self.load_label.setProperty("level", "low")
        elif load < 75:
            self.load_label.setProperty("level", "mid")
        else:
            self.load_label.setProperty("level", "high")
        self.load_label.style().unpolish(self.load_label)
        self.load_label.style().polish(self.load_label)
        self.count_label.setText(f"总帧数: {self._frame_count}")
        # 统计面板
        self.stat_panel.update_stats(
            load, fps, self._frame_count, self.trace_panel.view.id_summary()
        )

    @Slot(int)
    def _on_bitrate_changed(self, idx: int):
        br = self.BITRATES[idx]
        # 同步左侧 combo
        i = self.bitrate_combo.findData(br)
        if i >= 0:
            self.bitrate_combo.blockSignals(True)
            self.bitrate_combo.setCurrentIndex(i)
            self.bitrate_combo.blockSignals(False)
        if self._worker is not None:
            self._worker.set_bitrate_slot(br)

    @Slot(int)
    def _on_bitrate_combo_changed(self, idx: int):
        br = self.bitrate_combo.itemData(idx)
        if br is None: return
        i = self.BITRATES.index(br) if br in self.BITRATES else -1
        if i >= 0:
            self.tb_bitrate.blockSignals(True)
            self.tb_bitrate.setCurrentIndex(i)
            self.tb_bitrate.blockSignals(False)
        if self._worker is not None:
            self._worker.set_bitrate_slot(br)

    @Slot(list)
    def _on_filters_changed(self, filters):
        if self._worker is not None:
            self._worker.set_filters(filters)

    @Slot(object)
    def _on_send_frame(self, frame: CANFrame):
        if self._worker is None:
            self.status_label.setText("未连接，无法发送")
            return
        self._worker.send(frame)

    # ------------------------------------------------------------- 文件
    def _on_save_trace(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 Trace", "trace.csv",
            "CSV (*.csv);;JSON Lines (*.jsonl);;ASC (*.asc)")
        if not path:
            return
        if path.endswith(".csv"):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time", "ch", "can_id", "ext", "rtr", "dlc", "data_hex"])
                for fr in self.trace_panel.view._model._rows:
                    w.writerow([f"{fr.timestamp:.6f}", "CAN1",
                                f"{fr.can_id:X}", int(fr.extended),
                                int(fr.rtr), fr.dlc, fr.data.hex(' ').upper()])
        elif path.endswith(".jsonl"):
            with open(path, "w", encoding="utf-8") as f:
                for fr in self.trace_panel.view._model._rows:
                    f.write(json.dumps({
                        "time": fr.timestamp, "can_id": fr.can_id,
                        "extended": fr.extended, "rtr": fr.rtr,
                        "dlc": fr.dlc, "data": fr.data.hex(),
                    }) + "\n")
        else:
            # Vector ASC 风格（简化）
            with open(path, "w", encoding="utf-8") as f:
                f.write("date Wed Jan 01 00:00:00.000 2025\n")
                f.write("base hex  timestamps absolute\n")
                f.write("internal events logged\n")
                f.write("// version 13.0.0\n")
                f.write("Begin Triggerblock\n")
                t0 = self.trace_panel.view._model._rows[0].timestamp \
                    if self.trace_panel.view._model._rows else 0.0
                for fr in self.trace_panel.view._model._rows:
                    ts = fr.timestamp - t0
                    if fr.extended:
                        head = f"{fr.can_id:08X}x"
                    else:
                        head = f"{fr.can_id:03X}x" if fr.rtr else f"{fr.can_id:03X}"
                    d = " ".join(f"{b:02X}" for b in fr.data[:fr.dlc]) or "R"
                    f.write(f"{ts:9.6f} CAN1 {head} {d} Length {fr.dlc} CRC OK\n")
                f.write("End TriggerBlock\n")
        self.status_label.setText(f"Trace 已保存到 {path}")

    def _on_load_trace(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载 Trace", "", "CSV (*.csv);;JSON Lines (*.jsonl);;ASC (*.asc)")
        if not path:
            return
        try:
            if path.endswith(".csv"):
                with open(path, "r", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        fr = CANFrame(
                            can_id=int(row["can_id"], 16),
                            data=bytes.fromhex(row["data_hex"].replace(" ", "")),
                            extended=bool(int(row["ext"])),
                            rtr=bool(int(row["rtr"])),
                            timestamp=float(row["time"]),
                        )
                        self.trace_panel.append_frame(fr)
            elif path.endswith(".jsonl"):
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        d = json.loads(line)
                        fr = CANFrame(
                            can_id=d["can_id"],
                            data=bytes.fromhex(d["data"]),
                            extended=d.get("extended", False),
                            rtr=d.get("rtr", False),
                            timestamp=d["time"],
                        )
                        self.trace_panel.append_frame(fr)
            else:
                QMessageBox.information(self, "ASC", "ASC 文件请使用回放工具，暂不实现。")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def _on_save_send_list(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存发送列表", "send_list.json", "JSON (*.json)")
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.send_panel.to_dict_list(), f, indent=2)
        self.status_label.setText(f"发送列表已保存到 {path}")

    def _on_load_send_list(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载发送列表", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.send_panel.from_dict_list(json.load(f))
            self.status_label.setText(f"发送列表已加载: {path}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    # ------------------------------------------------------------ 快速发送
    def _on_quick_send(self):
        text, ok = QInputDialog.getText(
            self, "快速发送",
            "格式: ID,HEX_DATA    例:  0x123,DE AD BE EF 0A",
        )
        if not ok or not text.strip():
            return
        try:
            parts = [p.strip() for p in text.split(",")]
            can_id = int(parts[0], 16)
            data = bytes.fromhex(parts[1].replace(" ", "")) if len(parts) > 1 else b""
            extended = can_id > 0x7FF
            frame = CANFrame(can_id, data, extended=extended)
            self._on_send_frame(frame)
            self.status_label.setText(f"已发送: {frame}")
        except Exception as e:
            QMessageBox.warning(self, "格式错误", str(e))

    # ------------------------------------------------------------ 关闭
    def _on_about(self):
        QMessageBox.information(self, "关于 cangui",
            "<b>cangui</b><br>"
            "ZDT_CANable 2.0 PRO 上位机（cangaroo 风格）<br><br>"
            "基于 PySide6 / Qt 6 + 自研 gs_usb 驱动")

    def _restore_settings(self):
        bitrate = self._settings.value("bitrate", 500_000, int)
        if bitrate in self.BITRATES:
            i = self.BITRATES.index(bitrate)
            self.tb_bitrate.setCurrentIndex(i)
            self.bitrate_combo.setCurrentIndex(self.bitrate_combo.findData(bitrate))
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self._settings.value("state")
        if state:
            self.restoreState(state)
        # 自动扫描一次
        QTimer.singleShot(100, self._scan_devices)

    def closeEvent(self, e):
        self._settings.setValue("bitrate", self.bitrate_combo.currentData())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("state", self.saveState())
        if self._connected:
            self._disconnect()
        e.accept()
