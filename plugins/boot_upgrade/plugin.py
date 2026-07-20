"""STM32G4 Bootloader 升级插件入口。

导出 `create_plugin()` 供 PluginHost 加载。
负责：
1. 在 `init()` 中注册 i18n key（避免修改 cangui/i18n.py）
2. `build_widget()` 创建 BootUpgradePanel
3. `teardown_widget()` 调用 panel 的清理逻辑（发送 CANCEL）
4. 转发插件回调（on_connect / on_disconnect / on_frames / refresh_language）
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cangui.plugin_host import Plugin, PluginContext

from .widget import BootUpgradePanel, _I18N_KEYS


class BootUpgradePlugin(Plugin):
    """Boot 升级插件。"""

    name = "boot_upgrade"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[BootUpgradePanel] = None

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #
    def init(self, ctx: PluginContext) -> None:
        # 注册 i18n key（运行时合并到 cangui.i18n._TR）
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self) -> str:
        from cangui.i18n import _
        return _("Boot.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = BootUpgradePanel(ctx)
        return self._panel

    def confirm_close(self) -> bool:
        """用户请求关闭 Tab（非 force 路径）。
        升级进行中弹确认框，用户拒绝则阻止关闭。
        """
        if self._panel is None:
            return True
        try:
            return self._panel.confirm_close()
        except Exception:
            return True  # 异常时允许关闭，避免卡死

    def on_deactivating(self) -> None:
        """Tab 即将关闭：若升级进行中，取消升级。

        此时 widget 仍存在，可安全调用 panel 方法。
        UpgradeTask 在宿主 worker 线程上运行，cancel() 设置标志位即可。
        """
        if self._panel is None:
            return
        try:
            if self._panel._task is not None:
                self._panel._task.cancel()
        except Exception:
            pass

    def teardown_widget(self, widget: QWidget) -> None:
        widget.deleteLater()
        self._panel = None

    # ------------------------------------------------------------------ #
    #  回调转发
    # ------------------------------------------------------------------ #
    def on_connect(self) -> None:
        if self._panel is not None:
            self._panel.on_connect()

    def on_disconnect(self) -> None:
        if self._panel is not None:
            self._panel.on_disconnect()

    def on_frames(self, frames) -> None:
        pass  # Upgrader 自有 CAN 连接，不依赖宿主派发帧

    def refresh_language(self) -> None:
        if self._panel is not None:
            self._panel.refresh_language()


def create_plugin() -> BootUpgradePlugin:
    """PluginHost 通过此工厂函数实例化插件。"""
    return BootUpgradePlugin()
