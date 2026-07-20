"""CANable GUI 插件宿主 — 解耦接口。

本模块是 cangui 核心与扩展插件之间的唯一耦合点。提供：
- `Plugin`：插件契约基类（生命周期 + 可选回调）
- `PluginContext`：插件可访问的宿主能力（添加 Tab、发帧、读设置等）
- `PluginHost`：插件管理器（发现、加载、调度）

设计原则：
1. **零侵入扩展**：新增插件时无需修改 cangui 核心文件
   （main_window / worker / trace / send / filters）
2. **回调式解耦**：插件通过实现可选方法订阅事件，宿主统一调度
3. **生命周期清晰**：init → activate → (on_connect/on_disconnect/on_frames) → deactivate → shutdown
4. **资源可逆**：插件 Tab 关闭即反初始化，重新打开即重建

插件目录结构（项目根）::

    plugins/
    ├── __init__.py
    └── <plugin_name>/
        ├── __init__.py
        └── plugin.py      # 必须导出 `create_plugin() -> Plugin`

参考实现：plugins/boot_upgrade/
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import List, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QTabWidget, QWidget

from canable_sdk import CANFrame

logger = logging.getLogger("cangui.plugins")


# --------------------------------------------------------------------------- #
#  宿主能力
# --------------------------------------------------------------------------- #
class PluginContext:
    """插件可访问的宿主能力。所有方法均只允许主线程调用。

    通过本类访问主窗口能力，避免插件直接持有 MainWindow 引用而形成强耦合。
    """

    def __init__(self, main_window):
        self._mw = main_window

    @property
    def main_window(self):
        """仅用于只读访问主窗口属性（如 status bar）。"""
        return self._mw

    # ----- Tab 管理 -----
    def add_tab(self, title: str, widget: QWidget, plugin_name: str = "") -> int:
        """添加为中心 Tab，返回索引。

        plugin_name 用于为 tab 设置稳定 key（"plugin.<name>"），
        以便主程序记忆上次选中的 tab。
        """
        return self._mw._add_plugin_tab(title, widget, plugin_name=plugin_name)

    def remove_tab(self, widget: QWidget) -> None:
        """从中心 Tab 移除。"""
        self._mw._remove_plugin_tab(widget)

    def set_tab_title(self, widget: QWidget, title: str) -> None:
        idx = self._mw._center_tabs.indexOf(widget)
        if idx >= 0:
            self._mw._center_tabs.setTabText(idx, title)

    # ----- CAN 收发 -----
    def send_frame(self, frame: CANFrame) -> None:
        """通过 worker 线程安全队列发送一帧。仅在已连接时有效。"""
        self._mw._on_send_frame(frame)

    def is_connected(self) -> bool:
        return self._mw._connected

    def is_fd_mode(self) -> bool:
        """主界面 CAN FD 复选框状态。"""
        return self._mw.fd_chk.isChecked()

    def get_bitrate(self) -> int:
        return self._mw.bitrate_combo.currentData() or 500_000

    # ----- 设置持久化 -----
    def get_setting(self, key: str, default=None):
        """读取插件设置（自动加 `plugin.` 前缀，与核心设置隔离）。"""
        return self._mw._get(f"plugin.{key}", default)

    def set_setting(self, key: str, value) -> None:
        """写入插件设置（2s 防抖落盘到 settings.json）。"""
        self._mw._set(f"plugin.{key}", value)

    # ----- UI 反馈 -----
    def status_message(self, msg: str, timeout_ms: int = 0) -> None:
        """在状态栏显示消息。timeout_ms>0 时定时清除。"""
        if timeout_ms > 0:
            self._mw.statusBar().showMessage(msg, timeout_ms)
        else:
            self._mw.status_bar_set_text(msg)

    # ----- 升级任务 (供插件在 worker 线程上执行) -----
    def start_upgrade(self, task) -> None:
        """在 CAN worker 线程上执行升级任务。

        task 必须实现 ``run(bus: ZDTCanable)`` 方法。
        worker 线程会在下次循环迭代时调用 task.run(bus)，
        期间正常 CAN 收发暂停，完成后自动恢复。
        """
        if self._mw._worker is None:
            raise RuntimeError("CAN not connected")
        self._mw._worker.set_upgrade_task(task)

    # ----- i18n -----
    def register_i18n(self, key: str, zh: str, en: str) -> str:
        """注册一个 i18n key 并返回当前语言文本。后注册覆盖先注册。

        插件应在 `init()` 中注册所有 key，避免运行时 `_()` 找不到。
        建议使用插件名前缀（如 `Boot.Title`）避免冲突。
        """
        from .i18n import _TR, _
        _TR[key] = {"zh": zh, "en": en}
        return _(key)


# --------------------------------------------------------------------------- #
#  插件契约
# --------------------------------------------------------------------------- #
class Plugin(QObject):
    """插件基类。

    生命周期（由 PluginHost 调度）::

        init(ctx)                  — 应用启动一次：注册 i18n key、加载配置
        activate()                 — 用户打开 Tab：build_widget() → add_tab()
          on_activated()           — Tab 已显示，可开始工作
          on_connect()             — 仅 active 时收到（如启动时已连接）
          on_disconnect()          — 仅 active 时收到
          on_frames(frames)        — 仅 active 时收到批量帧（100ms 节流）
          refresh_language()       — 语言切换时刷新 UI
        deactivate()               — 用户关闭 Tab：on_deactivating() → remove_tab() → teardown_widget()
        shutdown()                 — 应用退出一次：若仍 active 先 deactivate

    子类必须实现：
        name             — 唯一标识（如 "boot_upgrade"）
        display_title()  — Tab 与菜单显示文本
        build_widget(ctx) — 构造 UI widget

    子类可选实现：
        teardown_widget(widget) — 默认调用 widget.deleteLater()
        on_activated / on_deactivating / on_connect / on_disconnect / on_frames / refresh_language
    """

    name: str = ""
    version: str = "0.1.0"

    def __init__(self):
        super().__init__()
        self._ctx: Optional[PluginContext] = None
        self._widget: Optional[QWidget] = None
        self._menu_action: Optional[QAction] = None

    # --- 由 PluginHost 调用 ---
    def _bind(self, ctx: PluginContext) -> None:
        self._ctx = ctx

    def _set_menu_action(self, action: QAction) -> None:
        self._menu_action = action

    # --- 生命周期 ---
    def init(self, ctx: PluginContext) -> None:
        """应用启动时调用一次。子类可重写以注册 i18n key、读取配置等。"""

    def activate(self) -> None:
        """打开 Tab。已激活则忽略。"""
        if self._widget is not None:
            return
        widget = None
        try:
            widget = self.build_widget(self._ctx)
            self._widget = widget
            self._ctx.add_tab(self.display_title(), widget, plugin_name=self.name)
            if self._menu_action is not None:
                self._menu_action.setChecked(True)
            self.on_activated()
            # 若启动时 CAN 已连接，补发 on_connect（文档承诺）
            try:
                if self._ctx.is_connected():
                    self.on_connect()
            except Exception:
                logger.exception("插件 %s 补发 on_connect 异常", self.name)
        except Exception:
            logger.exception("插件 %s 激活失败", self.name)
            # 完整清理：先 on_deactivating，再 remove_tab，最后 teardown
            if widget is not None:
                try:
                    self.on_deactivating()
                except Exception:
                    pass
                try:
                    if self._ctx is not None:
                        self._ctx.remove_tab(widget)
                except Exception:
                    pass
                try:
                    self.teardown_widget(widget)
                except Exception:
                    pass
            self._widget = None
            if self._menu_action is not None:
                self._menu_action.setChecked(False)

    def deactivate(self, force: bool = False) -> bool:
        """关闭 Tab 并释放资源。未激活返回 True。

        Args:
            force: True 时跳过 confirm_close 直接关闭（用于应用退出/取消升级等场景）。

        Returns:
            True 表示已关闭（或本来就未激活）；False 表示用户取消了关闭。
        """
        if self._widget is None:
            return True
        # 关闭确认（非 force 路径）
        if not force:
            try:
                if not self.confirm_close():
                    return False
            except Exception:
                logger.exception("插件 %s confirm_close 异常", self.name)

        widget = self._widget
        self._widget = None
        try:
            self.on_deactivating()
        except Exception:
            logger.exception("插件 %s on_deactivating 异常", self.name)
        try:
            self._ctx.remove_tab(widget)
        except Exception:
            pass
        try:
            self.teardown_widget(widget)
        except Exception:
            logger.exception("插件 %s teardown 异常", self.name)
        if self._menu_action is not None:
            self._menu_action.setChecked(False)
        return True

    def is_active(self) -> bool:
        return self._widget is not None

    # --- 可选回调（仅 active 时调用）---
    def on_activated(self) -> None:
        """Tab 已打开，可开始工作。"""

    def on_deactivating(self) -> None:
        """Tab 即将关闭，子类可在此停止定时器、发送 CANCEL 等。"""

    def confirm_close(self) -> bool:
        """用户请求关闭 Tab 时调用（非 force 路径）。
        返回 True 允许关闭，False 阻止关闭。默认允许。
        子类可重写以在有进行中操作时弹确认框。
        """
        return True

    def on_connect(self) -> None:
        """CAN 已连接。"""

    def on_disconnect(self) -> None:
        """CAN 已断开。"""

    def on_frames(self, frames: List[CANFrame]) -> None:
        """批量收到帧（100ms 节流，包含 TX echo 与 RX）。"""

    def refresh_language(self) -> None:
        """语言切换时刷新 UI 文本。"""

    # --- 应用退出 ---
    def shutdown(self) -> None:
        self.deactivate()

    # --- 子类必须实现 ---
    def display_title(self) -> str:
        return self.name

    def build_widget(self, ctx: PluginContext) -> QWidget:
        raise NotImplementedError

    def teardown_widget(self, widget: QWidget) -> None:
        widget.deleteLater()


# --------------------------------------------------------------------------- #
#  插件管理器
# --------------------------------------------------------------------------- #
class PluginHost:
    """插件管理器：自动发现、加载、生命周期调度。

    使用方式（在 MainWindow.__init__ 末尾）::

        self.plugins = PluginHost(self)
        self.plugins.load_all()
    """

    PLUGIN_DIR_NAME = "plugins"

    def __init__(self, main_window):
        self._mw = main_window
        self._ctx = PluginContext(main_window)
        self._plugins: List[Plugin] = []
        # active 状态防抖落盘
        self._save_timer = None  # 延迟创建，避免无 QTimer 环境

    @property
    def plugins(self) -> List[Plugin]:
        return list(self._plugins)

    # ----- 加载 -----
    def load_all(self) -> None:
        """扫描项目根 plugins/ 目录，自动加载所有插件子包。"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        plugins_dir = os.path.join(project_root, self.PLUGIN_DIR_NAME)
        if not os.path.isdir(plugins_dir):
            logger.info("插件目录不存在: %s", plugins_dir)
            return
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        for entry in sorted(os.listdir(plugins_dir)):
            if entry.startswith("_") or entry.startswith("."):
                continue
            full = os.path.join(plugins_dir, entry)
            if not os.path.isdir(full):
                continue
            if not os.path.isfile(os.path.join(full, "__init__.py")):
                continue
            if not os.path.isfile(os.path.join(full, "plugin.py")):
                continue
            plugin = self._load_one(entry)
            if plugin is None:
                continue
            try:
                self._register(plugin)
            except Exception:
                logger.exception("注册插件 %s 失败", entry)

        # 所有插件注册完成后，从 settings 恢复上次 active 的插件
        self._restore_active_state()

    def _load_one(self, pkg_name: str) -> Optional[Plugin]:
        try:
            mod = importlib.import_module(f"{self.PLUGIN_DIR_NAME}.{pkg_name}.plugin")
        except Exception:
            logger.exception("加载插件 %s 失败", pkg_name)
            return None
        if hasattr(mod, "create_plugin"):
            try:
                plugin = mod.create_plugin()
            except Exception:
                logger.exception("插件 %s create_plugin() 异常", pkg_name)
                return None
        else:
            # 兜底：找模块内 Plugin 子类
            plugin = None
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (isinstance(obj, type) and issubclass(obj, Plugin)
                        and obj is not Plugin and obj.__module__ == mod.__name__):
                    try:
                        plugin = obj()
                    except Exception:
                        logger.exception("插件 %s 实例化失败", pkg_name)
                        return None
                    break
            if plugin is None:
                logger.warning("插件 %s 未导出 create_plugin 或 Plugin 子类", pkg_name)
                return None
        return plugin

    def _register(self, plugin: Plugin) -> None:
        try:
            plugin._bind(self._ctx)
            # 先 init 让插件注册 i18n key，display_title() 才能拿到翻译文本
            plugin.init(self._ctx)
            action = QAction(plugin.display_title(), self._mw)
            action.setCheckable(True)
            action.setChecked(False)
            action.toggled.connect(lambda checked, p=plugin: self._on_action_toggled(p, checked))
            self._mw._add_plugin_menu_action(action)
            plugin._set_menu_action(action)
            self._plugins.append(plugin)
            logger.info("已加载插件: %s v%s", plugin.name, plugin.version)
        except Exception:
            logger.exception("注册插件 %s 失败", plugin.name)

    def _on_action_toggled(self, plugin: Plugin, checked: bool) -> None:
        if checked:
            plugin.activate()
        else:
            # 用户取消勾选菜单 → 走 confirm_close 流程，若用户拒绝则回滚勾选状态
            if not plugin.deactivate():
                # 用户取消了关闭，恢复菜单勾选
                if plugin._menu_action is not None:
                    plugin._menu_action.blockSignals(True)
                    plugin._menu_action.setChecked(True)
                    plugin._menu_action.blockSignals(False)
                return
        # 状态变化后异步保存（防抖）
        self._schedule_save_active()

    # ----- active 状态持久化 -----
    ACTIVE_SETTING_KEY = "plugin.active_list"

    def _restore_active_state(self) -> None:
        """从 settings 读取上次 active 的插件名列表，逐个激活。"""
        try:
            saved = self._mw._get(self.ACTIVE_SETTING_KEY, [])
        except Exception:
            saved = []
        if not isinstance(saved, list):
            return
        # 仅恢复仍存在的插件名（避免插件被删除后残留）
        valid_names = {p.name for p in self._plugins}
        for name in saved:
            if name not in valid_names:
                continue
            for p in self._plugins:
                if p.name == name and not p.is_active():
                    try:
                        p.activate()
                    except Exception:
                        logger.exception("恢复插件 %s active 状态失败", name)
                    break

    def _schedule_save_active(self) -> None:
        """防抖 500ms 保存当前 active 插件名列表。"""
        from PySide6.QtCore import QTimer
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(500)
            self._save_timer.timeout.connect(self._save_active_state)
        self._save_timer.start()

    def _save_active_state(self) -> None:
        names = [p.name for p in self._plugins if p.is_active()]
        try:
            self._mw._set(self.ACTIVE_SETTING_KEY, names)
        except Exception:
            logger.exception("保存插件 active 状态失败")

    def _save_active_state_now(self) -> None:
        """立即落盘 active 状态（应用退出时调用）。"""
        if self._save_timer is not None:
            self._save_timer.stop()
        self._save_active_state()

    # ----- Tab 关闭请求 -----
    def on_tab_close(self, widget: QWidget) -> bool:
        """中心 Tab 关闭请求。返回 True 表示已处理（找到对应插件并 deactivate）。

        若插件拒绝关闭（confirm_close 返回 False），返回 False 由调用方决定是否保留 Tab。
        """
        for p in self._plugins:
            if p._widget is widget:
                return p.deactivate()
        return False

    # ----- 事件分发（仅给 active 插件）-----
    def dispatch_frames(self, frames: List[CANFrame]) -> None:
        if not self._plugins or not frames:
            return
        for p in self._plugins:
            if not p.is_active():
                continue
            try:
                p.on_frames(frames)
            except Exception:
                logger.exception("插件 %s on_frames 异常", p.name)

    def dispatch_state(self, connected: bool, msg: str) -> None:
        for p in self._plugins:
            if not p.is_active():
                continue
            try:
                if connected:
                    p.on_connect()
                else:
                    p.on_disconnect()
            except Exception:
                logger.exception("插件 %s on_state 异常", p.name)

    def refresh_language(self) -> None:
        for p in self._plugins:
            try:
                p.refresh_language()
                if p._menu_action is not None:
                    p._menu_action.setText(p.display_title())
                if p.is_active() and p._widget is not None:
                    idx = self._mw._center_tabs.indexOf(p._widget)
                    if idx >= 0:
                        self._mw._center_tabs.setTabText(idx, p.display_title())
            except Exception:
                logger.exception("插件 %s refresh_language 异常", p.name)

    def shutdown(self) -> None:
        # 先把 active 状态立即落盘（不等防抖）
        try:
            self._save_active_state_now()
        except Exception:
            logger.exception("保存 active 状态异常")
        for p in self._plugins:
            try:
                # 应用退出：强制关闭，不走 confirm_close
                p.deactivate(force=True)
            except Exception:
                logger.exception("插件 %s shutdown 异常", p.name)
        self._plugins.clear()
