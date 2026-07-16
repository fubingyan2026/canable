"""CANable 2.5 主窗口。"""
from __future__ import annotations

import os
import csv
import json
import logging
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, QThread, Slot
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QMenu, QApplication,
                                QLabel, QComboBox, QPushButton, QSplitter, QFrame,
                                QListWidget, QListWidgetItem, QTabWidget,
                                QDockWidget, QStatusBar, QToolBar, QFileDialog,
                                QMessageBox, QInputDialog, QGroupBox, QFormLayout,
                                QCheckBox)

from PySide6.QtCore import QMutexLocker

from canable_sdk import ZDTCanable, CANFrame
from .style import set_theme, get_qss, current_theme, FG_ACCENT, FG_DIM, FG_WARN, FG_ERROR
from .i18n import _, language_changed, get_language, set_language
from .worker import CANWorker
from .trace import TracePanel
from .send import SendPanel

logger = logging.getLogger("cangui.main_window")
from .filters import FilterPanel

# --------------------------------------------------------------------------- #
#  主窗口
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    APP_NAME = "CANable2.5"
    ORG_NAME = "canable"
    WINDOW_TITLE = "CANable 2.5"

    BITRATES = [10_000, 20_000, 50_000, 100_000, 125_000, 250_000,
                333_000, 500_000, 800_000, 1_000_000]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CANable 2.5")
        self.resize(1400, 850)
        self.setDockOptions(self.dockOptions() & ~QMainWindow.AnimatedDocks)

        self._settings_dirty = False
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.timeout.connect(self._flush_settings)

        # 状态
        self._connected = False
        self._worker: Optional[CANWorker] = None
        self._frame_count = 0
        self._last_load = 0.0
        self._last_fps = 0
        self._noack_warning = False
        self._noack_timer = QTimer(self)
        self._noack_timer.setSingleShot(True)
        self._noack_timer.timeout.connect(self._clear_noack)
        self._connected_msg = ""
        self._settings = {}

        # 批量帧刷新定时器（主线程）
        # 100ms 间隔：稳定性优先，支持 ~5000 fps 不丢帧（受 MAX_BATCH=500 限制）
        self._batch_timer = QTimer(self)
        self._batch_timer.timeout.connect(self._on_batch_frames)
        self._batch_timer.start(100)

        self.__init_ui()

    def _settings_path(self):
        return os.path.join(os.path.dirname(self.send_panel.csv_path()), "settings.json")

    def _set(self, key, value):
        self._settings[key] = value
        if not self._settings_dirty:
            self._settings_dirty = True
            self._settings_timer.start(2000)

    def _flush_settings(self):
        if not self._settings_dirty:
            return
        self._settings_dirty = False
        self._settings_timer.stop()
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except Exception:
            pass

    def _get(self, key, default=None):
        return self._settings.get(key, default)

    def __init_ui(self):
        self._build_ui()
        self._build_menubar()
        self._build_statusbar()
        self._wire_signals()
        self._restore_settings()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # 中心：Tab
        self.trace_panel  = TracePanel(self)
        self.trace_panel.view.setAlternatingRowColors(True)
        center_tabs = QTabWidget()
        center_tabs.addTab(self.trace_panel, _("Trace.TabLabel"))
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
        self.send_dock = QDockWidget(_("Window.SendMessages"), self)
        self.send_dock.setObjectName("SendDock")
        self.send_dock.setWidget(self.send_panel)
        self.send_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.send_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.send_dock)

        # 右侧 Filter Dock
        self.filter_panel = FilterPanel(self)
        self.filter_dock = QDockWidget(_("Window.Filters"), self)
        self.filter_dock.setObjectName("FilterDock")
        self.filter_dock.setWidget(self.filter_panel)
        self.filter_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.filter_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.filter_dock)

    def _build_left_panel(self) -> QFrame:
        w = QFrame()
        w.setObjectName("sidebar")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        # 总线配置
        self._bus_box = QGroupBox(_("Left.Bus"))
        bf = QFormLayout(self._bus_box)
        self.bitrate_combo = QComboBox()
        bps = _("Left.BPS")
        for b in self.BITRATES:
            self.bitrate_combo.addItem(f"{b:,} {bps}", b)
        self.bitrate_combo.setCurrentText(f"500,000 {bps}")
        self._lbl_bitrate = QLabel(_("Left.Bitrate"))
        bf.addRow(self._lbl_bitrate, self.bitrate_combo)

        # CAN FD 选项
        self._lbl_canmode = QLabel(_("Left.CANMode"))
        self.fd_chk = QCheckBox(_("Left.CANFD"))
        self.fd_chk.toggled.connect(self._on_fd_toggle)
        bf.addRow(self._lbl_canmode, self.fd_chk)

        self.data_bitrate_combo = QComboBox()
        bps = _("Left.BPS")
        self.data_bitrate_combo.addItem(f"1,000,000 {bps}", 1_000_000)
        self.data_bitrate_combo.addItem(f"2,000,000 {bps}", 2_000_000)
        self.data_bitrate_combo.addItem(f"4,000,000 {bps}", 4_000_000)
        self.data_bitrate_combo.addItem(f"5,000,000 {bps}", 5_000_000)
        self.data_bitrate_combo.addItem(f"8,000,000 {bps}", 8_000_000)
        self.data_bitrate_combo.setEnabled(False)
        self._lbl_data_bitrate = QLabel(_("Left.DataBitrate"))
        self._lbl_data_bitrate.setEnabled(False)
        bf.addRow(self._lbl_data_bitrate, self.data_bitrate_combo)

        self.sample_combo = QComboBox()
        self.sample_combo.addItems([
            _("Left.Sample87"),
            _("Left.Sample75"),
            _("Left.Sample67"),
            _("Left.Sample50"),
        ])
        self._lbl_sample = QLabel(_("Left.SamplePoint"))
        bf.addRow(self._lbl_sample, self.sample_combo)
        layout.addWidget(self._bus_box)

        # 设备
        self._dev_box = QGroupBox(_("Left.Devices"))
        dv = QVBoxLayout(self._dev_box)
        self.device_list = QListWidget()
        dv.addWidget(self.device_list)
        self.scan_btn = QPushButton(_("Left.Scan"))
        self.scan_btn.clicked.connect(self._scan_devices)
        self.device_list.currentItemChanged.connect(self._on_device_selection_changed)
        dv.addWidget(self.scan_btn)
        self.connect_btn = QPushButton(_("Left.ConnectDevice"))
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._on_connect_toggle)
        dv.addWidget(self.connect_btn)
        layout.addWidget(self._dev_box, 1)

        return w

    def _build_menubar(self):
        mb = self.menuBar()

        self._menu_actions = []
        # File
        self._menu_file = file_menu = mb.addMenu(_("Menu.File"))
        act_open = QAction(_("File.OpenTrace"), self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._on_load_trace)
        file_menu.addAction(act_open)
        act_save = QAction(_("File.SaveTrace"), self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._on_save_trace)
        file_menu.addAction(act_save)
        file_menu.addSeparator()
        act_save_send = QAction(_("File.SaveSendList"), self)
        act_save_send.triggered.connect(self._on_save_send_list)
        file_menu.addAction(act_save_send)
        act_load_send = QAction(_("File.LoadSendList"), self)
        act_load_send.triggered.connect(self._on_load_send_list)
        file_menu.addAction(act_load_send)
        file_menu.addSeparator()
        act_quit = QAction(_("File.Exit"), self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # View
        view_menu = mb.addMenu(_("Menu.Windows"))
        self.act_toggle_send = self.send_dock.toggleViewAction()
        self.act_toggle_send.setText(_("Window.SendMessages"))
        self.act_toggle_filter = self.filter_dock.toggleViewAction()
        self.act_toggle_filter.setText(_("Window.Filters"))
        view_menu.addAction(self.act_toggle_send)
        view_menu.addAction(self.act_toggle_filter)

        # Tools
        tools_menu = mb.addMenu(_("Menu.Tools"))
        act_send_once = QAction(_("Tools.QuickSend"), self)
        act_send_once.setShortcut("Ctrl+Return")
        act_send_once.triggered.connect(self._on_quick_send)
        tools_menu.addAction(act_send_once)

        # Language submenu
        theme_menu = tools_menu.addMenu(_("Menu.Theme"))
        self.act_theme_light = QAction(_("Theme.Light"), self, checkable=True)
        self.act_theme_dark = QAction(_("Theme.Dark"), self, checkable=True)
        self.act_theme_light.setChecked(current_theme() == "light")
        self.act_theme_dark.setChecked(current_theme() == "dark")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        theme_group.addAction(self.act_theme_light)
        theme_group.addAction(self.act_theme_dark)
        theme_menu.addAction(self.act_theme_light)
        theme_menu.addAction(self.act_theme_dark)
        theme_group.triggered.connect(self._on_theme_changed)

        lang_menu = tools_menu.addMenu(_("Menu.Language"))
        self.act_lang_zh = QAction(_("Lang.Chinese"), self, checkable=True)
        self.act_lang_en = QAction(_("Lang.English"), self, checkable=True)
        self.act_lang_zh.setChecked(get_language() == "zh")
        self.act_lang_en.setChecked(get_language() != "zh")
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        lang_group.addAction(self.act_lang_zh)
        lang_group.addAction(self.act_lang_en)
        lang_menu.addAction(self.act_lang_zh)
        lang_menu.addAction(self.act_lang_en)
        lang_group.triggered.connect(self._on_language_changed)

        # Help
        help_menu = mb.addMenu(_("Menu.Help"))
        act_about = QAction(_("Help.About"), self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)



        # register actions for language refresh
        self._menu_actions = [
            (theme_menu, "Menu.Theme"),
            (lang_menu, "Menu.Language"),
            (self._menu_file, "Menu.File"),
            (view_menu, "Menu.Windows"),
            (tools_menu, "Menu.Tools"),
            (help_menu, "Menu.Help"),
            (act_open, "File.OpenTrace"),
            (act_save, "File.SaveTrace"),
            (act_save_send, "File.SaveSendList"),
            (act_load_send, "File.LoadSendList"),
            (act_quit, "File.Exit"),
            (act_send_once, "Tools.QuickSend"),
            (act_about, "Help.About"),
            (self.act_theme_light, "Theme.Light"),
            (self.act_theme_dark, "Theme.Dark"),
            (self.act_lang_zh, "Lang.Chinese"),
            (self.act_lang_en, "Lang.English"),
        ]
        QShortcut(QKeySequence("Ctrl+L"), self, self.trace_panel.clear_all)


    def _build_statusbar(self):
        sb: QStatusBar = self.statusBar()
        self.status_label = QLabel(_("Status.Disconnected"))
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("connected", False)
        sb.addWidget(self.status_label)

        sb.addPermanentWidget(QLabel("  "))
        self.bitrate_label = QLabel("— bps")
        sb.addPermanentWidget(self.bitrate_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.fps_label = QLabel(f"0 {_("Status.FPS")}")
        sb.addPermanentWidget(self.fps_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.load_label = QLabel(f"{_("Status.Load")} 0%")
        self.load_label.setObjectName("busLoad")
        sb.addPermanentWidget(self.load_label)

        sb.addPermanentWidget(QLabel("  |  "))
        self.count_label = QLabel(f"{_("Status.TotalFrames")}: 0")
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
            QMessageBox.critical(self, _("Left.Scan"), f"{_('Scan.Failed')}: {e}")
            self.connect_btn.setEnabled(False)
            return
        if not devs:
            item = QListWidgetItem(_("Left.NoDevice"))
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.device_list.addItem(item)
            self.connect_btn.setEnabled(False)
            return
        for d in devs:
            label = f"{d['manufacturer']} {d['product']}\n  S/N: {d['serial']}"
            li = QListWidgetItem(label)
            li.setData(Qt.UserRole, d)
            self.device_list.addItem(li)
        self.device_list.setCurrentRow(0)
        self.connect_btn.setEnabled(not self._connected)

    @Slot()
    def _on_device_selection_changed(self):
        if self._connected:
            return
        item = self.device_list.currentItem()
        self.connect_btn.setEnabled(item is not None and bool(item.flags() & Qt.ItemIsEnabled))

    # ----------------------------------------------------------- CAN FD
    @Slot(bool)
    def _on_fd_toggle(self, enabled: bool):
        self.data_bitrate_combo.setEnabled(enabled)
        self._lbl_data_bitrate.setEnabled(enabled)
        # 通知 send 面板更新 DLC 范围
        self.send_panel.set_fd_mode(enabled)

    # ----------------------------------------------------------- 连接
    @Slot()
    def _on_connect_toggle(self):
        if self._connected:
            self._disconnect()
        else:
            if self.device_list.currentItem() is None or not (self.device_list.currentItem().flags() & Qt.ItemIsEnabled):
                self.statusBar().showMessage(_("Left.NoDeviceSelected"), 3000)
                self.connect_btn.setChecked(False)
                return
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
        # 使用 _batch_timer 30ms 批量刷新，不连接逐帧 frame_received 信号
        self._worker.state_changed.connect(self._on_state_changed)
        self._worker.error.connect(self._on_error)
        self._worker.bus_stats.connect(self._on_bus_stats)
        self._worker.noack_warning.connect(self._on_noack_warning)
        # 同步过滤器
        self._worker.set_filters(self.filter_panel.filters)
        # 在独立线程跑 worker 的 connect() + run() 循环
        # 注意：worker 线程不设 parent，避免重复连接时旧线程未释放
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        # connect() 先执行（阻塞打开设备），成功后 run() 执行（阻塞循环）
        # 若 connect() 失败，_bus 为 None，run() 的 while 条件直接不满足
        self._worker_thread.started.connect(self._worker.connect)
        self._worker_thread.started.connect(self._worker.run)
        # 线程结束时清理 worker
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()
        self._update_connect_ui(True, _("Status.Connecting"))

    def _disconnect(self):
        if self._worker is None:
            return
        worker = self._worker
        thread = getattr(self, "_worker_thread", None)
        # 通知 worker 线程退出（run() 的 while 循环会在下次检查时退出，最多 10ms）
        with QMutexLocker(worker._mutex):
            worker._running = False
            worker._connected = False
        # 等待线程真正退出（最多 2 秒），避免僵尸线程
        if thread is not None:
            thread.wait(2000)
            # 若 wait 超时（线程卡在 USB 阻塞调用），terminate 作为最后手段
            if thread.isRunning():
                logger.warning("worker 线程未在 2s 内退出，强制终止")
                thread.terminate()
                thread.wait(1000)
        self._worker = None
        self._update_connect_ui(False, _("Status.Disconnected"))

    def _update_connect_ui(self, connected: bool, msg: str):
        self._connected = connected
        if connected:
            self._connected_msg = msg
        self.status_label.setText(msg)
        self.status_label.setProperty("connected", connected)
        # 重新应用属性样式
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.connect_btn.setChecked(connected)
        self.connect_btn.setText(_("Left.Disconnect") if connected else _("Left.ConnectDevice"))
        if not connected:
            item = self.device_list.currentItem()
            self.connect_btn.setEnabled(item is not None and bool(item.flags() & Qt.ItemIsEnabled))
        self.bitrate_combo.setEnabled(not connected)
        self.bitrate_label.setText(f"{self.bitrate_combo.currentData():,} {_('Left.BPS')}" if connected else f"— {_('Left.BPS')}")

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

    @Slot(str)
    def _on_noack_warning(self, msg: str):
        self._noack_warning = True
        self.status_label.setText(f"⚠ {_('Status.NoAck')}")
        self.status_label.setProperty("connected", False)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._noack_timer.start(1000)

    def _clear_noack(self):
        self._noack_warning = False
        self._update_connect_ui(self._connected, self._connected_msg)

    def _on_batch_frames(self):
        if self._worker is None:
            return
        batch = self._worker.take_batch()
        # throttle: limit frames per batch to prevent UI freeze
        MAX_BATCH = 1000
        if len(batch) > MAX_BATCH:
            batch = batch[-MAX_BATCH:]
        for frame in batch:
            self._frame_count += 1
            self.trace_panel.append_frame(frame)

    @Slot(float, int)
    def _on_bus_stats(self, load: float, fps: int):
        self._last_load = load
        self._last_fps = fps
        self.fps_label.setText(f"{fps} {_('Status.FPS')}")
        self.load_label.setText(f"{_('Status.Load')} {load:.1f}%")
        if load < 40:
            self.load_label.setProperty("level", "low")
        elif load < 75:
            self.load_label.setProperty("level", "mid")
        else:
            self.load_label.setProperty("level", "high")
        self.load_label.style().unpolish(self.load_label)
        self.load_label.style().polish(self.load_label)
        self.count_label.setText(f"{_("Status.TotalFrames")}: {self._frame_count}")



    def _on_bitrate_combo_changed(self, idx: int):
        br = self.bitrate_combo.itemData(idx)
        if br is None: return
        if self._worker is not None:
            self._worker.set_bitrate_slot(br)

    @Slot(list)
    def _on_filters_changed(self, filters):
        if self._worker is not None:
            self._worker.set_filters(filters)

    @Slot(object)
    def _on_send_frame(self, frame: CANFrame):
        if self._worker is None or not self._connected:
            self.status_label.setText(_("Error.NotConnected"))
            return
        # send() 将帧放入线程安全队列，由 worker 子线程在 run() 中实际发送
        self._worker.send(frame)

    # ------------------------------------------------------------- 文件
    def _on_save_trace(self):
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, _("File.SaveTraceTitle"), "trace.csv",
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
        self.status_label.setText(f"{_('File.TraceSaved')} {path}")

    def _on_load_trace(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, _("File.OpenTraceTitle"), "", "CSV (*.csv);;JSON Lines (*.jsonl);;ASC (*.asc)")
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
                QMessageBox.information(self, _("File.OpenTrace"), _("File.ASCNotSupported"))
        except Exception as e:
            QMessageBox.critical(self, _("File.LoadSendList"), f"{_('Load.Failed')}: {e}")

    def _on_save_send_list(self):
        self.send_panel.to_csv(self.send_panel.csv_path())
        self.status_label.setText(f"{_('File.SendListSaved')}: {self.send_panel.csv_path()}")

    def _on_load_send_list(self):
        if not self.send_panel.exists():
            self.status_label.setText(_("Scan.NoHistory"))
            return
        try:
            self.send_panel.from_csv(self.send_panel.csv_path())
            self.status_label.setText(f"{_('File.SendListLoaded')}: {self.send_panel.csv_path()}")
        except Exception as e:
            QMessageBox.critical(self, _("File.LoadSendList"), f"{_('Load.Failed')}: {e}")

    # ------------------------------------------------------------ 快速发送
    def _on_quick_send(self):
        text, ok = QInputDialog.getText(
            self, _("Tools.QuickSend"),
            _("Tools.QuickSendHint"),
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
            self.status_label.setText(f"{_('Tools.Sent')}: {frame}")
        except Exception as e:
            QMessageBox.warning(self, _("File.OpenTrace"), f"{_('Format.Error')}: {e}")

    # ------------------------------------------------------------ 关闭
    def _on_about(self):
        QMessageBox.information(self, _("Help.About"),
            "<b>CANable 2.5</b><br>" + _("About.Desc") + "<br><br>" + _("About.Tech"))

    def _restore_settings(self):
        try:
            with open(self._settings_path(), encoding="utf-8") as f:
                self._settings = json.load(f)
        except Exception:
            self._settings = {}
        s = self._settings
        bitrate = s.get("bitrate", 500_000)
        if bitrate in self.BITRATES:
            self.bitrate_combo.setCurrentIndex(self.bitrate_combo.findData(bitrate))
        self.fd_chk.setChecked(s.get("fd_mode", False))
        data_br = s.get("data_bitrate", 1_000_000)
        idx = self.data_bitrate_combo.findData(data_br)
        if idx >= 0:
            self.data_bitrate_combo.setCurrentIndex(idx)
        self.sample_combo.setCurrentIndex(s.get("sample_point", 0))
        self.trace_panel.autoscroll_chk.setChecked(s.get("autoscroll", True))
        if s.get("collapse", False):
            self.trace_panel.collapse_chk.setChecked(True)
        lang = s.get("language", "zh")
        theme = s.get("theme", "light")
        set_theme(theme)
        QApplication.instance().setStyleSheet(get_qss())
        set_language(lang)
        if hasattr(self, "act_lang_zh"):
            self.act_lang_zh.setChecked(lang == "zh")
            self.act_lang_en.setChecked(lang != "zh")
        if hasattr(self, "act_theme_light"):
            self.act_theme_light.setChecked(theme == "light")
            self.act_theme_dark.setChecked(theme == "dark")
        try:
            self.filter_panel.from_dict_list(s.get("filters", []), emit=False)
        except Exception:
            pass
        splitter_hex = s.get("splitter")
        if splitter_hex:
            self.splitter.restoreState(bytes.fromhex(splitter_hex))
        trace_hdr = s.get("trace_hdr")
        if trace_hdr:
            self.trace_panel.view.horizontalHeader().restoreState(bytes.fromhex(trace_hdr))
        send_hdr = s.get("send_hdr")
        if send_hdr:
            self.send_panel.table.horizontalHeader().restoreState(bytes.fromhex(send_hdr))
        filter_hdr = s.get("filter_hdr")
        if filter_hdr:
            self.filter_panel.table.horizontalHeader().restoreState(bytes.fromhex(filter_hdr))
        geometry = s.get("geometry")
        if geometry:
            self.restoreGeometry(bytes.fromhex(geometry))
        state = s.get("state")
        if state:
            self.restoreState(bytes.fromhex(state))
        # 恢复浮动 dock 的几何信息
        for name, dock in [("send_dock", self.send_dock), ("filter_dock", self.filter_dock)]:
            if s.get(f"{name}_floating"):
                geo = s.get(f"{name}_geo")
                if geo:
                    dock.setFloating(True)
                    dock.restoreGeometry(bytes.fromhex(geo))
        # 自动扫描一次
        QTimer.singleShot(100, self._scan_devices)
        if self.send_panel.exists():
            try:
                self.send_panel.from_csv(self.send_panel.csv_path())
            except Exception:
                pass
        self._refresh_language()


    def _on_theme_changed(self, action):
        name = "dark" if action == self.act_theme_dark else "light"
        set_theme(name)
        self._set("theme", name)
        QApplication.instance().setStyleSheet(get_qss())

    def _on_language_changed(self, action):
        self._set("language", "zh" if action == self.act_lang_zh else "en")
        set_language("zh" if action == self.act_lang_zh else "en")
        self._refresh_language()

    def _refresh_language(self):
        self.setWindowTitle("CANable 2.5")
        # menu actions
        if hasattr(self, "_menu_actions"):
            for item, key in self._menu_actions:
                if type(item).__name__ == "QMenu":
                    item.setTitle(_(key))
                else:
                    item.setText(_(key))
        # group boxes
        self._bus_box.setTitle(_("Left.Bus"))
        self._dev_box.setTitle(_("Left.Devices"))
        self.scan_btn.setText(_("Left.Scan"))
        self.connect_btn.setText(_("Left.Disconnect") if self._connected else _("Left.ConnectDevice"))
        # form labels
        self._lbl_bitrate.setText(_("Left.Bitrate"))
        self._lbl_data_bitrate.setText(_("Left.DataBitrate"))
        self._lbl_sample.setText(_("Left.SamplePoint"))
        self._lbl_canmode.setText(_("Left.CANMode"))
        self.fd_chk.setText(_("Left.CANFD"))
        # status bar
        if hasattr(self, "fps_label"):
            self.fps_label.setText(f"{self._last_fps} {_('Status.FPS')}")
            self.load_label.setText(f"{_('Status.Load')} {self._last_load:.0f}%")
            self.count_label.setText(f"{_('Status.TotalFrames')}: {self._frame_count}")
            self.status_label.setText(_("Status.Connected") if self._connected else _("Status.Disconnected"))
        # docks
        self.send_dock.setWindowTitle(_("Window.SendMessages"))
        self.filter_dock.setWindowTitle(_("Window.Filters"))
        # center tab
        if hasattr(self, "_center_tabs"):
            self._center_tabs.setTabText(0, _("Trace.TabLabel"))
        if hasattr(self, "act_toggle_send"):
            self.act_toggle_send.setText(_("Window.SendMessages"))
            self.act_toggle_filter.setText(_("Window.Filters"))
        # sub-panels
        if hasattr(self, "trace_panel") and hasattr(self.trace_panel, "refresh_language"):
            self.trace_panel.refresh_language()
        if hasattr(self, "send_panel") and hasattr(self.send_panel, "refresh_language"):
            self.send_panel.refresh_language()
        if hasattr(self, "filter_panel") and hasattr(self.filter_panel, "refresh_language"):
            self.filter_panel.refresh_language()
        # refresh device list text
        if hasattr(self, "device_list"):
            if self.device_list.count() == 1:
                item = self.device_list.item(0)
                if item and not (item.flags() & Qt.ItemIsEnabled):
                    item.setText(_("Left.NoDevice"))
            elif self.device_list.count() == 0:
                item = QListWidgetItem(_("Left.NoDevice"))
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.device_list.addItem(item)
        # refresh combo items — blockSignals 避免触发 currentIndexChanged 改波特率
        if hasattr(self, "bitrate_combo"):
            bps = _("Left.BPS")
            current_data = self.bitrate_combo.currentData()
            self.bitrate_combo.blockSignals(True)
            self.bitrate_combo.clear()
            for b in self.BITRATES:
                self.bitrate_combo.addItem(f"{b:,} {bps}", b)
            if current_data:
                self.bitrate_combo.setCurrentIndex(self.bitrate_combo.findData(current_data))
            self.bitrate_combo.blockSignals(False)
        if hasattr(self, "data_bitrate_combo"):
            bps = _("Left.BPS")
            current_data = self.data_bitrate_combo.currentData()
            self.data_bitrate_combo.blockSignals(True)
            self.data_bitrate_combo.clear()
            for b in [1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000]:
                self.data_bitrate_combo.addItem(f"{b:,} {bps}", b)
            if current_data:
                self.data_bitrate_combo.setCurrentIndex(self.data_bitrate_combo.findData(current_data))
            self.data_bitrate_combo.blockSignals(False)
        # refresh sample combo
        if hasattr(self, "sample_combo"):
            current_text = self.sample_combo.currentText()
            self.sample_combo.blockSignals(True)
            self.sample_combo.clear()
            self.sample_combo.addItems([
                _("Left.Sample87"),
                _("Left.Sample75"),
                _("Left.Sample67"),
                _("Left.Sample50"),
            ])
            idx = self.sample_combo.findText(current_text)
            if idx >= 0:
                self.sample_combo.setCurrentIndex(idx)
            self.sample_combo.blockSignals(False)

    def closeEvent(self, e):
        if not hasattr(self, 'bitrate_combo'):
            e.accept()
            return
        self._set("bitrate", self.bitrate_combo.currentData())
        self._set("fd_mode", self.fd_chk.isChecked())
        self._set("data_bitrate", self.data_bitrate_combo.currentData())
        self._set("sample_point", self.sample_combo.currentIndex())
        self._set("autoscroll", self.trace_panel.autoscroll_chk.isChecked())
        self._set("collapse", self.trace_panel.collapse_chk.isChecked())
        self._set("theme", current_theme())
        self._set("language", get_language())
        self._set("filters", self.filter_panel.to_dict_list())
        self._set("splitter", bytes(self.splitter.saveState().toHex()).decode())
        self._set("trace_hdr", bytes(self.trace_panel.view.horizontalHeader().saveState().toHex()).decode())
        self._set("send_hdr", bytes(self.send_panel.table.horizontalHeader().saveState().toHex()).decode())
        self._set("filter_hdr", bytes(self.filter_panel.table.horizontalHeader().saveState().toHex()).decode())
        self._set("geometry", bytes(self.saveGeometry().toHex()).decode())
        self._set("state", bytes(self.saveState().toHex()).decode())
        # 保存浮动 dock 的几何信息（位置+尺寸）
        for name, dock in [("send_dock", self.send_dock), ("filter_dock", self.filter_dock)]:
            if dock.isFloating():
                self._set(f"{name}_floating", True)
                self._set(f"{name}_geo", bytes(dock.saveGeometry().toHex()).decode())
            else:
                self._set(f"{name}_floating", False)
        self._flush_settings()
        try:
            self.send_panel.to_csv(self.send_panel.csv_path())
        except Exception:
            pass
        if self._connected:
            self._disconnect()
        e.accept()
